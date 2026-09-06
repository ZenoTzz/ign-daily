import XCTest

final class AppFlowTests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }
    func testDemoWorkspaceArticleAndTabs() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--demo"]
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["工作台"].waitForExistence(timeout: 15))
        let row = app.buttons["article.1"]
        XCTAssertTrue(row.waitForExistence(timeout: 10))
        capture(app, name: "工作台")
        row.tap()
        XCTAssertTrue(app.staticTexts["原生阅读 · 本地演示"].waitForExistence(timeout: 10))
        capture(app, name: "文章阅读")
        app.navigationBars.buttons.element(boundBy: 0).tap()
        for name in ["任务", "词库", "我的"] {
            let tab = app.tabBars.buttons[name]
            XCTAssertTrue(tab.exists)
            tab.tap()
            XCTAssertTrue(tab.isSelected)
            capture(app, name: name)
        }
    }
    func testDemoPolishEditSaveAndReopen() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--demo"]
        app.launch()
        let article = app.buttons["article.1"]
        XCTAssertTrue(article.waitForExistence(timeout: 15))
        article.tap()
        let edit = app.buttons["article.edit"]
        XCTAssertTrue(edit.waitForExistence(timeout: 10))
        edit.tap()
        let title = app.descendants(matching: .any).matching(identifier: "译文标题").firstMatch
        XCTAssertTrue(title.waitForExistence(timeout: 10))
        title.tap()
        title.typeText(" UI regression")
        let changedTitle = try XCTUnwrap(title.value as? String)
        XCTAssertTrue(changedTitle.contains("UI regression"))
        let save = app.navigationBars.buttons["保存"]
        XCTAssertTrue(save.isEnabled)
        save.tap()
        let saved = app.staticTexts["已保存到服务器润色副本，可在网站读取。"]
        for _ in 0..<8 {
            if saved.exists { break }
            app.swipeUp()
        }
        XCTAssertTrue(saved.waitForExistence(timeout: 5))
        XCTAssertFalse(save.isEnabled)
        capture(app, name: "编辑润色已保存")
        app.navigationBars.buttons["关闭"].tap()
        XCTAssertTrue(edit.waitForExistence(timeout: 5))
        edit.tap()
        XCTAssertTrue(title.waitForExistence(timeout: 10))
        XCTAssertEqual(title.value as? String, changedTitle)
        capture(app, name: "编辑润色")
        app.navigationBars.buttons["关闭"].tap()
    }
    func testDemoTranslationSubmission() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--demo"]
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["工作台"].waitForExistence(timeout: 15))
        let selection = app.buttons["select.3"]
        for _ in 0..<4 {
            if selection.exists && selection.isHittable { break }
            app.swipeUp()
        }
        XCTAssertTrue(selection.exists)
        selection.tap()
        let start = app.buttons["开始翻译"]
        XCTAssertTrue(start.waitForExistence(timeout: 5))
        start.tap()
        let confirm = app.buttons["提交翻译"]
        XCTAssertTrue(confirm.waitForExistence(timeout: 5))
        confirm.tap()
        XCTAssertTrue(app.alerts["翻译请求已提交"].waitForExistence(timeout: 10))
        capture(app, name: "演示翻译提交")
        app.alerts.buttons["查看任务"].tap()
        XCTAssertTrue(app.tabBars.buttons["任务"].isSelected)
    }
    private func capture(_ app: XCUIApplication, name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
