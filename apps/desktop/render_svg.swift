// Renders an SVG verbatim to a PNG: render_svg <in.svg> <out.png> <width> [height].
// Height defaults to width (square icon sizes); the status-bar mark passes its own aspect.
// Used by build.py for the icon sizes that orbit-icon.png cannot be downsampled to.
import AppKit

let args = CommandLine.arguments
guard args.count == 4 || args.count == 5, let px = Int(args[3]), let py = Int(args.count == 5 ? args[4] : args[3]),
      let image = NSImage(contentsOf: URL(fileURLWithPath: args[1])) else {
    FileHandle.standardError.write("usage: render_svg <in.svg> <out.png> <width> [height]\n".data(using: .utf8)!); exit(2)
}
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: py, bitsPerSample: 8,
                           samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                           bytesPerRow: 0, bitsPerPixel: 0)!
rep.size = NSSize(width: px, height: py)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
NSGraphicsContext.current?.imageInterpolation = .high
image.draw(in: NSRect(x: 0, y: 0, width: px, height: py))
NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: args[2]))
