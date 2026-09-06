# IGN Daily for iPhone

SwiftUI 原生操作端，连接 `https://igndaily.site/api`。采集、翻译、质量检查和后台任务继续在服务器执行。

## 当前可用功能

- 网站账号登录，Bearer token 保存到本机 Keychain；退出清理登录状态。
- 按新闻日期查看、搜索、筛选、批量选文；提交前用文章 URL 重新核对当前 ID。
- 任务列表与逐篇进度；仅在任务页可见且 App 前台时轮询，重新打开恢复服务器状态。
- 中文、英文和逐段对照阅读，原文配图及系统分享。
- 润色标题、副标题、摘要和正文；保存服务器润色副本，并通过 revision 检查防止覆盖另一端更新。
- 词库搜索、候选提交、审批和驳回。

学习周报、模型配置、多模型比较、Google Docs 管理和复杂导出仍通过网页工作台完成；APNs 推送、完整离线资料库和 App Store/TestFlight 分发尚未实现。润色保存不等于 Google Docs 已同步，也不会自动采纳为长期风格规则。

## 构建

要求完整 Xcode 和 iOS SDK；部署目标 iOS 17+，iPhone。

直接打开 `IGNDaily.xcodeproj`，选择 IGNDaily scheme 和 iPhone 模拟器后 Run。

工程源配置是 `project.yml`。添加文件后可使用已安装的 XcodeGen 重新生成：

```bash
xcodegen generate --spec ios/project.yml
xcodebuild -project ios/IGNDaily.xcodeproj -scheme IGNDaily \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -derivedDataPath /tmp/ign-daily-derived CODE_SIGNING_ALLOWED=NO test
```

以上命令在仓库根目录运行。实际可用模拟器以 `xcrun simctl list devices available` 为准。

## 演示与正式连接

Debug 构建可以在 scheme 的 Run → Arguments 加入 `--demo`。所有 API 调用会被本地 URLProtocol 拦截，演示提交和编辑不会访问生产服务器；工作台显示“本地演示”。不添加参数时连接真实服务器，使用网站账号登录。

演示实现仅编入 DEBUG，不把演示参数作为生产身份。网络层使用 ephemeral URLSession，不保存私有 API 响应，不自动重试写请求，不跟随 HTTP 重定向。发生提交超时，应先查看任务列表确认服务器是否已接收。

## 真机签名

不需要付费开发者账号就可以先用 Personal Team 在自己的设备上调试：

1. Xcode → Settings → Accounts，登录普通 Apple ID。
2. 用数据线连接并解锁 iPhone，选择信任；按系统提示启用 Developer Mode。
3. 工程的 IGNDaily target → Signing & Capabilities，选择自己的 Personal Team，保持 Automatically manage signing。
4. 如默认 Bundle Identifier 被占用，改成自己唯一的反向域名标识，再选择连接的 iPhone 点 Run。

免费签名通常约 7 天需要重新从 Xcode 安装，且设备/应用数量受 Apple 限制。TestFlight 与正式上架需要付费计划。没有用户 Apple ID 和设备授权时不能代替用户完成真机签名。

本次已使用用户 Personal Team 为连接的 iPhone Air（iOS 27 beta）构建并安装成功。内嵌描述文件允许该设备，签名有效期至北京时间 2026-09-13 14:15。首次启动需要在 iPhone 的“设置 → 通用 → VPN 与设备管理”中信任对应开发者。设备启动验证状态见下方验收记录。

真机构建必须选择实际连接的设备作为 destination，并使用 `-allowProvisioningUpdates -allowProvisioningDeviceRegistration`。首次使用 generic iOS destination 得到的描述文件没有包含此 iPhone；选择真实设备后 Xcode 自动生成正确的描述文件并完成签名，不需要撤销或删除其他证书。

## 验证与生产对应

2026-09-06 在 Xcode 26.6 / iOS 26.5 / iPhone 17 Pro 模拟器完成：

- App 构建成功；10 项单元测试、3 条 UI 流程测试通过。
- 覆盖 snake_case 解码、源图兼容、401、409 不重试、显式 null 修订、润色 CAS、新闻日 08:00 边界、ID/URL 映射及冲突请求不重试。
- UI 覆盖文章阅读与四个主标签、演示选文提交、编辑保存并重新打开验证。
- 后端 42 项测试、脚本 65 项测试通过；相同后端代码在生产隔离目录再跑 42 项测试通过。
- 生产发布后首页 200，API health 正常，未登录访问新润色接口返回 401。
- 14:20 已在用户 iPhone Air（iOS 27 beta）完成安装、开发者信任并通过 devicectl 成功启动真实服务器版本；设备签名验证通过。

完整网站账号的真实读写流程仍需用户登录验收；测试没有发起真实模型调用。原有仓库汇率快照过期使 agent_doctor 总体失败，生产汇率已验证更新，此次没有覆盖运行时数据。

新移动端依赖 `/articles/{date}/{id}/polish` 和 `/translations/request` 省略 trigger_workflow 时按服务端实时配置执行的行为。接口合约维护在 `server_api/API.md`。

服务器本次已部署对应 API 与 Service Worker v13；数据备份 `/srv/ign-daily-backups/ign-daily-20260906-141158.tar.gz`，旧代码备份 `/srv/ign-daily-backups/mobile-api-20260906-141200/code.tar.gz`。生产数据、数据库和密钥未被代码包覆盖。

原生客户端与配套后端修复在同一仓库中维护。后续部署必须保留移动端所需的新接口；不要单独回退后端而继续使用依赖新接口的 App。现有自动部署 workflow 的完整版本回滚问题仍待单独整改。
