import Foundation

@main
struct DevServerChecks {
    static func main() throws {
        for (input, expected) in [
            (" 192.168.1.20:9407 ", "http://192.168.1.20:9407"),
            ("http://100.64.0.20:9192/", "http://100.64.0.20:9192"),
            ("https://192.168.1.20:443", "https://192.168.1.20"),
            ("[fd00::20]:9407", "http://[fd00::20]:9407"),
        ] {
            let actual = try DevServerAddress.parse(input)
            precondition(actual.absoluteString == expected)
        }
        for input in ["", "localhost:9407", "example.com:9407", "192.168.1.20", "192.168.1.20:0",
                      "192.168.1.20:65536", "192.168.1.20:abc", "192.168.1.20:9407/api",
                      "http://user:pass@192.168.1.20:9407", "file://192.168.1.20:9407",
                      "192.168.1.20:9407?token=secret", "192.168.1.20:9407#fragment",
                      "192.168.1.20:9407\n/path", "999.999.999.999:9407"] {
            do {
                _ = try DevServerAddress.parse(input)
                fatalError("Accepted invalid dev address")
            } catch DevServerAddress.AddressError.invalid { }
        }
        print("Dev server address checks passed")
    }
}
