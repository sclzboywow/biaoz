# V2.0：可信标准源采集与状态同步版

V2.0 目标：以国标电子书库等可信标准源为状态锚点，同步标准资源元数据、现行/废止状态、分类路径、详情页证据和变更信息，再用这些可信源数据校准本地文件库。

## 可信源

默认可信源：

- 名称：国标电子书库
- Base URL：https://ebook.chinabuilding.com.cn
- 信任等级：A
- 信任分：100
- 状态权威：是
- 采集模式：目录页 + 详情页

合规边界：

系统优先采集公开展示的标准元数据、状态、分类、目录、变更信息和详情页证据。如需全文访问，应通过合法账号、机构授权或人工上传方式维护，不绕过登录、IP 授权或付费限制批量下载全文。

参考页面：

- [国标电子书库资源列表](https://ebook.chinabuilding.com.cn/zbooklib/sublibBook/resultlist?SiteID=1&viewType=imgView)
- [国标电子书库资源详情示例](https://ebook.chinabuilding.com.cn/zbooklib/book/detail/show?SiteID=1&bookID=155902)

## 核心模块

1. 可信源管理
2. 源分类体系同步
3. 标准资源列表同步
4. 详情页深度采集
5. 本地文件匹配
6. 现行/废止状态校准
7. 变更监测
8. 状态冲突复核

## 新增数据表

V2.0 已新增表：

- `trusted_sources`
- `source_categories`
- `standard_resources`
- `standard_details`
- `standard_file_matches`
- `standard_change_logs`
- `source_status_sync_logs`

## 状态模型

V2.0 文件状态判断拆成三层：

```text
source_status：可信源状态
system_status：系统综合研判状态
manual_status：人工确认状态
```

优先级：

```text
人工锁定状态 > 可信源状态 > 系统规则 > AI 辅助判断
```

## 本地文件匹配规则

优先级：

1. 标准编号完全一致
2. 标准编号 + 名称相似
3. 名称高度相似 + 发布/实施日期一致
4. 文件名包含编号和名称
5. AI 相似度辅助判断

当前已实现基础接口：

```http
POST /api/v1/standard-file-matches/run
```

该接口先按标准编号完全一致匹配本地文件和可信源资源。

## 页面

V2.0 已增加页面入口：

- 可信源资源库
- 本地文件匹配
- 变更监测

后续页面：

- 资源详情页
- 状态冲突页面
- 可信源分类同步页面

## 后续实现顺序

1. 列表页解析器：同步编号、名称、资源类型、状态、发布日期、实施日期、废止日期、简介、关键词、详情页 URL。
2. 详情页解析器：同步入库日期、主编单位、目录、强制性条文、变更信息、PDF 试读链接。
3. 变化检测：字段变化写入 `standard_change_logs`。
4. 状态校准：匹配本地文件后写入 `source_status_sync_logs`，并按规则生成提醒。
5. 状态冲突复核：只展示本地状态和可信源状态冲突的文件。

## V2.0 验收标准

- 能同步可信源资源列表。
- 能采集详情页公开证据。
- 能按编号自动匹配本地文件。
- 能用可信源状态校准本地文件状态。
- 能记录变化日志和状态同步日志。
- 能把未匹配、匹配冲突、状态冲突放入人工复核。
