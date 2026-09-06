import XCTest
@testable import IGNDaily

final class NewsDayTests: XCTestCase {
    func testBeijingEightAMBoundaryIndependentOfDeviceTimezone() throws {
        let iso = ISO8601DateFormatter()
        XCTAssertEqual(NewsDay.current(at: try XCTUnwrap(iso.date(from: "2026-09-05T23:59:59Z"))), "2026-09-05")
        XCTAssertEqual(NewsDay.current(at: try XCTUnwrap(iso.date(from: "2026-09-06T00:00:00Z"))), "2026-09-06")
        XCTAssertEqual(NewsDay.current(at: try XCTUnwrap(iso.date(from: "2026-01-01T00:00:00Z"))), "2026-01-01")
        XCTAssertEqual(NewsDay.current(at: try XCTUnwrap(iso.date(from: "2025-12-31T23:59:59Z"))), "2025-12-31")
    }
}
