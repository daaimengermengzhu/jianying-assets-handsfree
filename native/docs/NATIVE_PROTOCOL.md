# 原生协议与调用边界

验证范围：2026-09-23 至 2026-09-30。平台：Windows；引擎基线：11.5.0.14471。本文保留该版本的实测参数和失败边界，不保证其他版本兼容。验证结果汇总见 [实测结果](VALIDATION.md)。

## 架构

```text
CLI / stdio MCP
    ↓
Python 校验、复制主媒体、管理自己的后台子进程
    ↓ JSON lines
安装目录自带 Bun + 本项目 native-host.cjs
    ↓
安装目录自带 videoeditor_addon.node → 原生剪辑引擎
```

`CREATE_NO_WINDOW` 启动自己的进程；不向当前 GUI 注入 DLL、不点击界面、不修改 GUI 当前项目。退出卡住时最多等待 5 秒，只终止自己启动的子进程。

## 调用约定

原生 addon 导出包括 `initialize`、`invoke`、`readFrame`、`shutdown`。`initialize` 参数是 JSON 字符串，含 `modelsDir`，实测返回 `admissible:true`、`qtRequired:false`、`serverStarted:true`。这些字段说明初始化成功，不代表渲染和导出可用。

通用请求是 JSON：`id`、`domain`、`operation`、`params`、可选 `targetId`、`protocolVersion:1`、`priority:interactive`。

player 域在 addon 层使用 `method` 及 `sessionId`；本项目 host 负责转换，顶层参数和 `params` 同时传入，与安装包自带 service 的约定一致。

| 领域 / 操作 | 关键参数与返回 |
| --- | --- |
| `draft / readFile` | 同时提供绝对文件 `path` 与父目录 `rootPath`。返回 `content` JSON 字符串、`encrypted`、`cipherType` |
| `draft / writeFile` | `path`、`rootPath`、JSON 字符串 `content`、`encrypted:true` |
| `player / create` | `kind:draft`、`serviceGeneration:1`；返回动态 `sessionId` |
| `player / load` | `draftPath`、`workspacePath`；绑定上述会话 |
| `edit / draft.setCanvasSize` | `ratio:"9:16"`；返回真实 `draftSnapshot` |
| `edit / video.add` | 本地 `path`、微秒 `duration/sourceDuration/sourceStartTime/startTime`、`trackIndex`、`needInsertTargetTrack`、`segmentId` |

编辑返回的 `draftSnapshot` 需要再通过原生 writeFile 保存。不能把 `accepted:true` 单独当作效果成功：最初传 width/height 得到 accepted，但画布没变；传 ratio 才产生真正的 1080×1920 快照。

## 素材与保存

原草稿中的音频路径格式是 `##_draftpath_placeholder_<id>_##/textReading/<file>.wav`。直接把草稿 JSON 复制到别处，原生 load 会按新草稿目录解析，导致缺少音频。

当前实现先从原草稿位置解析并复制视频/音频主媒体到新目录的 Resources，再替换路径。导出快照后检查每个主媒体文件存在；字幕和音频段数保留；重新读取的完整 JSON 等于保存内容；原文件 SHA-256 不变。

## 独立 addon 尚未解决的部分

- CEF/GPU 状态在隔离进程中为 unavailable。CPU 取帧实验出现空包或阻塞；缺失音频已修复，但不能据此宣称取帧问题解决。
- addon 当前没有已经识别、验证的 MP4 导出入口。DLL 中存在导出相关符号不等于已有正确的 ABI、初始化环境或可用的自动导出能力。
- 输出的 native 草稿重新读取已验证；同版本 11.5 的独立测试项目 GUI 打开和导出也已通过。通用 GUI 列表登记、旧版本兼容仍未验证。

完整时间线后台预览尚未通过，不出现在可用 MCP 工具中。源视频抽帧和音频波形已经单独验证并提供工具。

## 缓存素材与网页桥接（2026-09-28）

实测 `edit/sticker.add` 的 `params.segInfo.material.path/name` 会进入返回素材；顶层 `params.path/name` 不生效。三轨草稿使用 `trackIndex:3` 可创建独立贴纸轨。资源类型、真实 ID、视觉效果仍未验证，不应把此参数片段当作完整贴纸添加协议。

安装目录下 `Resources/image_h5_material_shop/static/js/` 的来源：

- `async/346.8a533ead.js`：`addTimeline`、`getFilterFrame`、`getTimelineFrame`；素材类型枚举 Filter=12；滤镜面板 `filter-c`。
- `955.be541d82.js`：`/artist/v1/panel/get_panel_info`、`/artist/v1/effect/get_resources_by_category_id`、`/artist/v1/effect/mget_item`。主机 `https://lv-pc-api.ulikecam.com`。通过 `JSBridge.call("request", ...)` 发送，指定公共参数和请求签名；只是静态确认，未在线调用。
- `207.00441865.js`：Windows 侧依赖 `window.cefQuery({request:JSON.stringify({callType,data}), ...})`，回调进入 `window.JSBridge._handleCallbackFromNative`。独立 Bun/Node 环境没有这个宿主注入函数；知道方法名不等于建立了调用通道。

使用缓存素材前须检查包完整性；缺文件时停止，不能通过跳过校验或补造资源 ID 继续写入。路径能写入快照不代表权益、素材绑定或渲染已验证。

## 已验证的宿主 HTTP 桥接（2026-09-28 后续）

来源：同版本 `app-server.mjs` 的 discovery/health/session 实现，以及 `app/` 下 `ai-creation~28.a0e13ae1.js` 模块 69546、音色模块的调用参数。Windows 使用系统临时目录中的 `infinite-canvas-native-bridge.json`。仅在内存读取其 port 与本地 token，使用客户端规定的认证头；绝不记录凭据或转发到外网。不硬编码端口。

- `GET /.infinite-canvas-native-bridge/health`：返回 `ok:true`。不要原样返回 `local_agent_server`，它可能含内部认证信息。
- `POST /infinite-canvas/session`，body `{}`：创建独立会话，得到 `session_id`。
- `POST /infinite-canvas/session/{session_id}/jsb`，body `{method, params}`：封装仅开放已验证的方法；最初验证下列三个只读方法，后续扩展见下文。
- `getUserSubcriptionInfo`，params `{}`：返回 `data.user_info`；输出仅保留会员标记与 credits。
- `getToneCategories`，params `{}`：返回 `data.tabs`，本次 20 类。
- `getToneList`，params `{keyword,offset:0,count,includeUnsupported:false}`：返回 `data.resources`。已确认响应 keyword 与输入一致；原生服务本次仍返回 50 条，因此应用层再限制输出数量。
- `DELETE /infinite-canvas/session/{session_id}`：清理本次会话，返回 `ok:true`。

进程运行并登录是当前前提；未验证关闭界面后持续可用。此前发现的 7302 端口对普通 HTTP GET 超时，不是此次成功使用的桥接地址；数据同步命名管道未写入任何请求。

初期三项 MCP 工具均返回成功，音色查询包含“解说小帅”，`limit=0` 在本地拒绝。该阶段未生成语音或控制桌面，不覆盖生成、扣费预检、滤镜或导出。

## 后续验证：正常签名请求、配音与素材

通过相同会话的 JSB `request`，由宿主签名发送固定路由请求。params 为 `url`、`method:POST`、`needCommonParams:true`、`header_signing:true`、JSON Content-Type 和字符串 `data`。返回 `data.encodeData` 需要 URI 解码再 JSON 解析；HTTP 200 且业务 ret=0 才接受。实现只允许验证过或实验中明确识别的固定路由，不提供任意代理工具。

- `panel/get_panel_info` 使用 `panel:filter-c/default-c/text-template-c`。
- `effect/get_resources_by_category_id` 使用 `category_id,offset,count`。素材位于 `effect_item_list[].common_attr`；会员标记取自 `business_info.json_str`。外部输出省略签名、URL 和创作者帐号。
- 集合条目 type=112 不是单个滤镜；`collection.resources` 给出子素材 `id,effect_type,source`，通过 `effect/mget_item` 获取详情。不要将其他 API 的类型编号与素材商店枚举混用。
- 暮信真实滤镜 type=12，ID `7279061785922080055`；包 URL 来自 `item_urls`，`download_info.url` 可能为空。获取后校验目录 MD5。
- SystemTTS 走 `/lv/v1/web/common_task/new` 与 `query`；任务 type=10000、req_key=pc_canvas_tool、task_version=v3，payload 包含 cap_key=pc_canvas_tool_collect 和 cap_json。后者为 `biz_scene:tts,model:SystemTTS,text,tone_info:{tone_speaker,tone_effect_id}`。
- 任务句柄 id/token 只保存在内存，查询成功后从 `result` 或 `payload` 解析 media；不能只读 result。音频下载不附带帐号凭据。每次只创建一个短任务，不自动重新提交。

目录与配音通过真实 stdio 验证，“解说小帅”生成 6.336 秒 MP3，测试前后余额未变，不代表未来调用免费。滤镜通过快照填入资源后原生保存，重新读取含 1 条 filter 轨片段，主媒体无缺失；不等于 `filter.add` 参数已正确，视觉效果仍未验证。

## 2026-09-29 搜索参数修正与新分界

之前 `/artist/v1/effect/search` 的两种猜测请求被业务码 1000 拒绝；现从客户端 `ai-creation~27.6b6e58c4.js` 找到完整参数并在线验证：

```json
{"app_id":3704,"count":3,"effect_type":7,"query":"闪光","offset":0,"need_recommend":false,"filter_optional":{"filter_paid_type":[]},"pack_optional":{"need_contract":true,"need_favorite_info":true},"search_id":"","search_option":{"filter_uncommercial":false},"statistics_optional":{},"strategy_extra":""}
```

已通过真实 MCP 验证搜索类型：effect=7、transition=19、subtitle-template=48、sound=3、material=201、music=4、sticker=2、text-template=6、recipe=50。201 的 `search_option` 加 `scene:material_lib_c_v2,sticker_type:0`，响应是实际资源类型（视频为5），详情查询使用实际类型。不要将旧枚举里的 Music=5 用到此 API。recipe 返回素材组合，不等于智能包装全流程。

`getToneList` 也支持 `{categoryId:'37478',categoryKey:'malevoice',offset:0,count:50,includeUnsupported:false}`。从该分类发现真人播客男的公开会员标记，ID 7516817692729331007、speaker zh_male_dayi_saturn_bigtts；已通过 MCP 实际生成 5.448 秒 MP3，测试前后余额未变。

素材 URL 选择逻辑来源同 JS 的资产适配器：视频对象优先 `video.transcoded_video` 中正常提供的最大版本，再 origin_video；其次 common_attr.extra.Resources；然后 download_info.url、item_urls、file_url。贴纸 type=2 例外：download_info 可能为 GIF 预览，应优先 item_urls 中原始 ZIP，MD5 对应后者。只有来自同一原始包的 MD5 才能用于包校验，转码文件不能用原包 MD5。八类在线资源获取已通过，另获取字幕所需字体。音乐 song.duration 为秒（本样例122），duration_ms 可能为0；优先有效 duration_ms，否则换算秒。

客户端退出会导致 `ConnectionRefused`；重新打开客户端后在线验证成功。调用前应检查宿主是否运行。

## 2026-09-29 原生素材写入与 MCP

`draft_assets.py` 将正常账号资源获取、独立草稿编辑、严格绑定检查、加密写入和读回封装成一个操作，支持 effect、sound、music、transition。客户端在线以取得素材；编辑使用独立 native 进程。所有输出新建，不覆盖源文件，不修改 GUI 索引。

以下均通过实际返回快照和 MCP 验证。时间单位为微秒，CLI/MCP 的毫秒参数在进入此处前乘1000。

| 操作 | 正确参数 |
| --- | --- |
| effect.add | trackIndex、trackId、segmentId、targetTimeRange:{start,duration}、applyType:0；material:{path,name,resId,resourceId,effectId,type:18,sourcePlatform:0,adjustParams:[]} |
| audio.add（音效） | audioPath、audioTitle、audioId、resourceId、type:6、duration/sourceDuration/sourceStartTime/startTime、trackId、targetTrackIndex、needInsertTargetTrack:true、segmentId、volume |
| audio.add（音乐） | 同音效，type:4；返回材料类型为 music；默认音量0.15 |
| video.setTransition | segId/segmentId、duration、path、name、resourceId、effectId、sourcePlatform:0、isOverlap:false；要求同轨相邻画面 |

`targetTrackIndex` 是音频轨相对索引，不能直接传全轨数量。特效 material.type=18 才返回 video_effect；按 JS 枚举传17会返回 beauty。此处是当前 C++ 绑定的实测编号，不概括为所有版本一致。所有添加均检查新素材资源 ID、路径、类型以及片段引用/时长；转场还检查前一段 extra_material_refs 引用了对应素材。

初步测试不能只检查 accepted：贴纸 segInfo.material 虽保存路径但类型为 none、时长0；字幕 templateResource 的调用未写入 caption_template_info 的 ID/path，均判失败、不交付输出。滤镜完整原生参数仍未确定。真实 MP4 经媒体解析确认有效，但 video.add 超时；已有 JPG 添加仍通过。

四种素材已按顺序合并到一个 9.566666 秒草稿并加密读回。后续客户端导出验证见下一节。

## 2026-09-29：宿主媒体与导出备用流程

参数来源为安装包 `Resources/canvas_agent/app/static/js/ai-creation~28.a0e13ae1.js` 模块 35991；MCP 封装只开放验证过的固定方法，不提供任意 JSB 调用。

| 方法 | 已验证参数 | 已验证返回 |
| --- | --- | --- |
| getFileInfo | `{paths:[绝对本地路径]}` | code=1，data.result 中 exist=true；仅实验使用 |
| extractMediaFrames | `{path,width:320,height:180,timestamps:[1000]}` | code=1，data.images[].timestamp；url 字段实际是 PNG 原始 base64，而不是下载地址 |
| getAudioWaveformData | `{path,start_ms:0,duration_ms:5400,max_points:32}` | code=1，fulfilled=true、partial=false、wave_data_enable=true、point_count=32、values 为真实采样 |

时间参数单位为毫秒。`host_media.py` 校验本地文件、类型、时间/尺寸边界、PNG signature/块长度/CRC/IEND 以及波形完整性和有限数值。PNG 保存到独立 UUID 文件；不接受返回的任意 HTTP 地址，不输出 base64 或内部字段。当前限制单帧最多 921600 像素，单边至多 1280；波形区间至多 600000ms、请求点数16–4096。

`jianying_extract_video_frame` 和 `jianying_audio_waveform` 通过真实 stdio MCP。这条路径读的是已经存在的媒体文件，没有解决未渲染草稿的时间线预览。

### 独立渲染再次核对

分别使用项目目录、安装目录作为工作目录初始化，两者均 admissible=true，但 cefGpuState=unavailable；GPU capability result=-112、failureStage=1、failureReason=2，supportsCpuFallback=true。`refreshCurrentFrame` 虽在 JS 服务允许列表中，当前 addon 实际返回 invalid_action_id。直接 load 后调用 readFrame 返回零字节；先前 seek 在12秒上限超时。不能把 supportsCpuFallback=true 当作实际渲染成功。

### 正常绑定草稿后的 exportDraft

前端模块 7143 的 session 创建明确支持 `{draft_path,draft_id}`。`createDraft` 在前端桥接层实际转为创建绑定会话，不应盲目将其视为同名 JSB 请求。

绑定已有项目时，`draft_id` 应来自原生读取 `draft_meta_info.json` 的字段；它与 `Timelines/project.json.id`、`draft_content.json.id` 不同。本轮首次按 project.json.id 校验发现返回 ID 不符，立即停止后续导出调用；原生读取元数据核实正确 ID 后重新绑定，精确核对路径及 ID。

空会话 `exportDraft({})` 返回 code=-3 invalid parameter。正确绑定测试草稿后返回 code=1 success，data 为空；读取该会话事件只观察到 showWebMask，未取得完成文件或导出任务结果。**这只是请求受理证据，后台导出仍未验证成功。** 自建会话已删除。没有改写宿主鉴权或接管别的会话。

### 实际通过的客户端路径

客户端验证使用专门新建的空白项目。关闭项目回到首页后，先验证项目身份、零时长、零轨道，再完整备份目录。仅替换根目录及主时间线的两份 `draft_content.json`，沿用客户端建立的目录、索引和时间线身份；原生写入后完整读回，源草稿保持不变。

这是受特定空白工程约束的实验流程，**不得原样用于任意用户已有项目，也不能在项目仍被编辑时写入文件**。通用导入仍需身份校验和冲突处理。

重新打开后画面、字幕和音频时间线正常，客户端导出设置显示3项会员权益。通过界面实际导出唯一命名的本地 MP4，未发布到平台。结果为9.59秒、720×1280、HEVC、AAC 44.1kHz双声道；整段解码通过。后台取帧验证图像和转场，波形验证有效音轨。外部媒体工具仅用于检查，没有承担剪映渲染。

## 2026-09-29 晚至 30 日：本地 DataSdk 和加密草稿二次编辑

新增 `data-sdk-host.cjs` 从当前安装包 `canvas_agent/app/static/js` 的 webpack 模块工厂定位唯一导出 DataSdk 的模块。只加载本机代码、执行模型层；没有 browser、cefQuery、fetch 或帐号上下文。输入来自临时快照，输出也是临时模型对照数据；真正的最终草稿仍由原生组件加密保存。

重要差异：SDK recoveryDraft/getDraftStr 会忽略原生 effect 轨并增删默认材料；不能把整个 SDK 输出当最终草稿。现在保留原生完整数据，比较 SDK action 前后，再只合并所选段/文字材料的变化，以及新片段所引用的新材料依赖。未引用的 vocal_beautifys 等默认物不会被带入。普通字幕改字用单一全范围样式的保守修改，按 UTF-16 更新范围，停用自动 TTS，保留原音轨和关联。

| 操作 | 本机已验证路径 |
| --- | --- |
| sticker | 先 track.add 创建明确的 sticker 轨，再 sticker.add({trackIndex,segInfo:{segId,timeRange,material,clip}})；检查 type、资源 ID、时长和独立轨道。直接调用原生 C++ 同名操作不是这个路径 |
| subtitle-template | text.updateSubtitleTemplate，传目标 segId、syncToAll:false、applyKeywordsStyle:false、applyFontSize:false；templateResource 包含 resourceItemParam、content.json 原文、fonts 资源 ID 和真实 TTF 路径；只改所选字幕 |
| stock-video | video.add 的 videos[] 经过 createVideoParamFromPlain；size、clip、mediaInfo 也使用对应模型构造；源素材 ID 在 materialId，序列化后是 materials.videos[].material_id，不能误查 resource_id |

模板包类型 48、字体类型 10、视频素材类型 5、贴纸类型 2；文字模板类型 6 与字体不同。官方视频用已有 ffprobe 确认尺寸、帧率、时长和音轨，按原草稿微秒 duration 精确追加，避免毫秒取整造成缝隙。读取到 GUI 的省略字段时，缺少 start 意为 0。

安装包 SDK 有 onAbort 后仍返回 ok:true 的情况，桥接层必须以任一 abort 为失败。试过的 text.setMaterials 仍有这种失败，因此没有包装该调用为改字能力。

`jianying_replace_caption` 和 `jianying_apply_cached_asset` 已完成真实四步 MCP 链、19 项本地测试。原音频/特效/转场严格相等，原始文件哈希不变。客户端将新贴纸从 40% 放大到 160% 后保存，后台读回确认为 1.6，并成功再次改字幕和加密保存。

导出新片段由客户端界面完成：12.585011 秒、720×1280、HEVC + AAC、5,059,858 字节；完整解码通过，1、3.2、11 秒抽帧对应贴纸/改字、字幕模板、官方城市视频。首次宿主波形返回不完整，工具拒绝；最终音频以 WAV PCM 全解码确认有效，峰值 19672/32768。

另外定位 app-server.mjs 内部评估调用 `lyra-cli draft export --ref --output --timeout`，其 workspace 环境变量按源代码指向项目。仅查询导出 help 的实际执行仍返回 -100015 unauthorized host process，未绕过鉴权。内部入口存在与当前能够无界面调用是两个不同结论。

## 2026-09-30：批量执行、整体交付和导出结论

`batch_edits.py` 在一个NativeSession中只读取一次源稿，按序处理1–100项受限操作；缓存素材使用批内私有ModelSession复用安装包模型环境。每项动作仍独立创建DataSdk实例，onAbort仍算失败。通过选择性合并保留SDK会丢弃的原始字段。

`model_edits._save` 改为同父目录内临时写入、完整加密读回、再次核对源稿哈希、最终目录rename。目标已存在或并发出现即拒绝覆盖；异常只清理自己创建的临时目录。此保护覆盖批量、单次改字和已缓存素材工具；旧的make_portrait/add_catalog_asset暂未迁移。

新增MCP `jianying_edit_batch`、`jianying_timeline`，当前17项。支持普通改字、三类缓存素材、既有片段transform和volume；timeline分页暴露必要ID和参数并检查已用依赖。transform的scale写入clip.scale.x/y，x/y写入clip.transform，rotation为clip.rotation；volume写入对应片段volume。真实MCP和完整加密读回已验证，本轮未验证渲染。

内部导出命令接受 `--ref`、`--output`、`--timeout`。使用正确工作区环境及 15 秒超时参数实测，1.04 秒返回 `-100015`，无文件，源稿不变。没有调用会上传预览视频的评估接口。当前使用客户端人工预览、导出。

### 批量参数与限制

先用 `jianying_timeline` 获取真实 `segment_id`，再提交 `jianying_edit_batch(source_draft, output_name, operations)`；`operations` 为按序执行的数组，包含 1–100 项。

| action | 必填字段 | 可选字段与范围 |
| --- | --- | --- |
| replace-caption | segment_id、text | 1–200 字，单一完整样式，保留原配音；按 UTF-16 计算 emoji 范围 |
| apply-cached-asset | kind、asset_manifest | kind 为 sticker/subtitle-template/stock-video；可带 segment_id、start_ms、duration_ms、font_manifest、source_start_ms |
| transform | segment_id | 至少一项 scale/x/y/rotation；统一缩放 0.01–10；x/y 为原生归一化坐标 -2–2；角度 -360–360 |
| volume | segment_id、volume | 音频或视频片段，0–2；1 为原音量 |

素材清单来自 `retrieve_asset` 正常获取并校验的资源。字幕模板必须指定目标字幕及匹配的字体清单；stock-video 仅在末尾追加，可选择源视频起点，时长至多 30 秒。普通改字不支持混合样式、共享文字素材或复杂 `base_content`，不会重新配音。

批内新增片段尚无别名引用机制，需取得返回 ID 后在下一批调整。主媒体可解析原路径；其他未处理的相对依赖或远程依赖明确拒绝，要求有效的绝对本地依赖。时间线分页检查已使用素材的路径、字体及主引用。超时后关闭自己的处理进程，不复用失去同步的会话。

性能、回归结果与缺口见 [实测结果](VALIDATION.md)。原生包、用户素材、解密快照和个人记录不随源码发布。
