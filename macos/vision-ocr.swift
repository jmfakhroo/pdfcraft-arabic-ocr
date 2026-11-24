// vision-ocr: Arabic OCR with Apple's Vision framework (the engine behind Live Text),
// printing Tesseract-style TSV so PdfCraft can use it in place of Tesseract.
//
//   vision-ocr <image> [tsv|txt]
//
// Languages: $VISION_OCR_LANGS (comma list, default "ar-SA"), e.g. "ar-SA,en-US".
//
// Gap filling: Vision is far more accurate than Tesseract on Arabic body text, but on some
// lines (bold quotations in «») it garbles words into "%!%!%" or skips the line entirely.
// Tesseract (Arabic model) also reads the page; its lines are used only where Vision has no
// clean line. $VISION_OCR_HYBRID=0 turns this off; $VISION_OCR_TESS_LANGS (default "ara").
// Build: swiftc -O vision-ocr.swift -o ~/.local/bin/vision-ocr

import AppKit
import Foundation
import Vision

func fail(_ msg: String) -> Never {
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
    exit(1)
}

let args = CommandLine.arguments
guard args.count >= 2 else { fail("usage: vision-ocr <image> [tsv|txt]") }
let mode = args.count >= 3 ? args[2] : "tsv"

guard let img = NSImage(contentsOf: URL(fileURLWithPath: args[1])),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil)
else { fail("vision-ocr: can't read image \(args[1])") }
let W = Double(cg.width), H = Double(cg.height)

let langs = (ProcessInfo.processInfo.environment["VISION_OCR_LANGS"] ?? "ar-SA")
    .split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }

let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.recognitionLanguages = langs
req.usesLanguageCorrection = true
do { try VNImageRequestHandler(cgImage: cg, options: [:]).perform([req]) }
catch { fail("vision-ocr: recognition failed: \(error)") }

// Vision's boxes are normalized with a bottom-left origin; TSV wants pixels from the top-left.
func px(_ r: CGRect) -> (Int, Int, Int, Int) {
    let l = max(0, r.minX * W), t = max(0, (1 - r.maxY) * H)
    return (Int(l.rounded()), Int(t.rounded()), Int((r.width * W).rounded()), Int((r.height * H).rounded()))
}


struct Word { var text: String; var box: (Int, Int, Int, Int); var conf: Int }
struct Line { var box: (Int, Int, Int, Int); var words: [Word]; var source: String }

// Vision lines, top to bottom.
let obs = (req.results ?? []).sorted { $0.boundingBox.maxY > $1.boundingBox.maxY }
var vlines: [Line] = []
for o in obs {
    guard let c = o.topCandidates(1).first else { continue }
    let s = c.string
    var ranges: [Range<String.Index>] = []
    var idx = s.startIndex
    while idx < s.endIndex {
        while idx < s.endIndex, s[idx].isWhitespace { idx = s.index(after: idx) }
        guard idx < s.endIndex else { break }
        var end = idx
        while end < s.endIndex, !s[end].isWhitespace { end = s.index(after: end) }
        ranges.append(idx..<end)
        idx = end
    }
    let total = max(1, s.count)
    var words: [Word] = []
    for r in ranges {
        var box: CGRect? = (try? c.boundingBox(for: r))?.boundingBox
        if box == nil || box!.width <= 0 {
            // Fallback: share the line's width by character position (right-to-left).
            let a = Double(s.distance(from: s.startIndex, to: r.lowerBound)) / Double(total)
            let b = Double(s.distance(from: s.startIndex, to: r.upperBound)) / Double(total)
            let lb = o.boundingBox
            box = CGRect(x: lb.maxX - b * lb.width, y: lb.minY, width: (b - a) * lb.width, height: lb.height)
        }
        words.append(Word(text: String(s[r]).replacingOccurrences(of: "\t", with: " "), box: px(box!), conf: Int(Double(c.confidence) * 100)))
    }
    if !words.isEmpty { vlines.append(Line(box: px(o.boundingBox), words: words, source: "vision")) }
}

// Junk Vision produces on lines it can't read: runs of %!#… symbols.
let junkSet = Set("%!#$&*@^_=<>|~\\")
func junkCount(_ s: String) -> Int { s.filter { junkSet.contains($0) }.count }
func isJunkWord(_ s: String) -> Bool { let j = junkCount(s); return j > 0 && j * 2 >= s.count }
func lineIsBad(_ l: Line) -> Bool { junkCount(l.words.map(\.text).joined()) >= 2 }
func hasArabicLetter(_ s: String) -> Bool {
    s.unicodeScalars.contains { (0x0620...0x064A).contains($0.value) || (0x066E...0x06D3).contains($0.value) }
}

// Same printed line? Mostly overlapping vertically, and touching horizontally.
func sameLine(_ a: (Int, Int, Int, Int), _ b: (Int, Int, Int, Int)) -> Bool {
    let top = max(a.1, b.1), bottom = min(a.1 + a.3, b.1 + b.3)
    let left = max(a.0, b.0), right = min(a.0 + a.2, b.0 + b.2)
    guard bottom > top, right > left else { return false }
    return Double(bottom - top) >= 0.5 * Double(max(1, min(a.3, b.3)))
}

func tesseractLines(_ path: String) -> [Line] {
    // Homebrew on Apple silicon, then on Intel.
    guard let tess = ["/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"]
        .first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else { return [] }
    let p = Process()
    p.executableURL = URL(fileURLWithPath: tess)
    p.arguments = [path, "stdout", "-l", ProcessInfo.processInfo.environment["VISION_OCR_TESS_LANGS"] ?? "ara", "tsv"]
    var env = ProcessInfo.processInfo.environment
    env["OMP_THREAD_LIMIT"] = "1"
    p.environment = env
    let pipe = Pipe()
    p.standardOutput = pipe
    p.standardError = FileHandle.nullDevice
    do { try p.run() } catch { return [] }
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    guard p.terminationStatus == 0, let text = String(data: data, encoding: .utf8) else { return [] }
    var order: [String] = []
    var lines: [String: Line] = [:]
    for row in text.split(separator: "\n").dropFirst() {
        let f = row.split(separator: "\t", omittingEmptySubsequences: false).map(String.init)
        guard f.count >= 12, let l = Int(f[6]), let t = Int(f[7]), let w = Int(f[8]), let h = Int(f[9]) else { continue }
        let key = "\(f[2]).\(f[3]).\(f[4])"
        if f[0] == "4" {
            lines[key] = Line(box: (l, t, w, h), words: [], source: "tesseract"); order.append(key)
        } else if f[0] == "5", let conf = Double(f[10]), conf >= 0 {
            let word = f[11].trimmingCharacters(in: .whitespaces)
            if !word.isEmpty { lines[key]?.words.append(Word(text: word, box: (l, t, w, h), conf: Int(conf))) }
        }
    }
    return order.compactMap { lines[$0] }.filter { ln in
        // Only real text lines: Arabic letters and a decent average confidence (drops the
        // noise Tesseract reads in calligraphy, ornaments and pictures).
        let arabic = ln.words.filter { hasArabicLetter($0.text) }
        guard !arabic.isEmpty else { return false }
        let mean = Double(ln.words.map(\.conf).reduce(0, +)) / Double(ln.words.count)
        return mean >= 55 && Double(arabic.count) >= 0.5 * Double(ln.words.count)
    }
}

var lines = vlines
if ProcessInfo.processInfo.environment["VISION_OCR_HYBRID"] != "0" {
    let good = vlines.filter { !lineIsBad($0) }
    var bad = vlines.filter { lineIsBad($0) }
    var added: [Line] = []
    for t in tesseractLines(args[1]) where !good.contains(where: { sameLine($0.box, t.box) }) {
        bad.removeAll { sameLine($0.box, t.box) }   // Tesseract's reading replaces a garbled one
        added.append(t)
    }
    lines = good + bad + added
}
// Whatever junk is left becomes nothing rather than "%!%!%".
lines = lines.map { var l = $0; l.words = l.words.filter { !isJunkWord($0.text) }; return l }.filter { !$0.words.isEmpty }
lines.sort { $0.box.1 < $1.box.1 }

if mode == "txt" {
    for l in lines { print(l.words.map(\.text).joined(separator: " ")) }
    exit(0)
}

var out = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
out += "1\t1\t0\t0\t0\t0\t0\t0\t\(Int(W))\t\(Int(H))\t-1\t\n"
for (i, l) in lines.enumerated() {
    let n = i + 1
    out += "4\t1\t1\t1\t\(n)\t0\t\(l.box.0)\t\(l.box.1)\t\(l.box.2)\t\(l.box.3)\t-1\t\n"
    for (j, w) in l.words.enumerated() {
        out += "5\t1\t1\t1\t\(n)\t\(j + 1)\t\(w.box.0)\t\(w.box.1)\t\(w.box.2)\t\(w.box.3)\t\(w.conf)\t\(w.text)\n"
    }
}
FileHandle.standardOutput.write(out.data(using: .utf8)!)
