# 变频器故障查询（施耐德）

手机浏览器打开即用：输入故障代码，或拍一张变频器面板照片，给出故障说明、可能原因和处理办法。
不需要登录，访问 `http://服务器IP:8080` 即可。

## 工作方式

```
故障代码 / 照片 ──► 大模型读图取代码 ──► 查手册知识库 ──► 大模型按手册条目用中文回答
```

- 回答只依据 `data/` 里整理的手册条目和管理员录入的本厂资料，库里没有的代码会明确说明，不会编造。
- 大模型可选：Claude、OpenAI 兼容接口（OpenAI、通义千问、DeepSeek 等）、本地 Ollama。
- 不配置大模型也能用，只是直接显示手册条目原文，且不能识别照片。

## 已收录的系列

条目均整理自施耐德**中文版**编程手册，页码范围见各 `data/*.psv` 文件头部的 `source` 行。

| 系列 | 条目数 | 来源 |
|---|---|---|
| ATV12 | 43 | ATV12 User Manual BBV28581（英文版） |
| ATV312 | 26 | ATV312 编程手册 BBV46388 |
| ATV320 | 60 | ATV320 编程手册 NVE41300 |
| ATV340（御卓） | 115 | ATV340 编程手册 NVE61649 |
| ATV600（ATV630/650/660/680 等） | 134 | ATV600 编程手册 EAV64324（P～V 开头的条目为摘要改写） |
| ATV61 | 73 | Altivar 61 Programming Manual（英文版整理） |
| ATV610 | 77 | ATV610 编程手册 EAV64393 |
| ATV71 | 71 | ATV71 编程手册 1755859 |

警告码（Warning，如 FFDA、THA）尚未收录，目前只有故障码（Error）。
没有收录的型号、手册里没有的代码，可以让管理员在“管理页”里补充（见下一节）。

> 条目是对官方手册的整理，部分文字为意译，现场处理请以原版手册为准。

## 排查经验层（让本地小模型也能答得像样）

小模型最缺的不是手册，而是“遇到这个故障先查什么、怎么判断”的经验。程序把这部分放在大模型之外：

- `data/expert/families.json` 里按故障机理分了 15 类（过流、短路接地、过压、欠压缺相、电机过载、变频器过热、输出缺相、超速堵转、模拟量丢失、通信、外部/安全回路、内部故障、配置、温度传感器、工艺类），
  每类写了原理、按现场概率排序的原因及判断方法、排查步骤（测什么、怎么测）、禁忌、什么时候停手找厂家。这是通用经验，不是手册原文，回答里会标“（经验）”。
- 查询时，程序按故障代码、手册条目的用词、你在“补充说明”里写的现象（如“减速时跳”“下雨以后”）自动判断属于哪一类，把对应清单交给大模型，
  大模型只负责组织语言和结合本厂资料，不必靠自己“懂变频器”。
- 没有配置大模型时，也会直接显示这份排查清单。只写现象、没有代码也能给出排查思路。
- `LLM_PROFILE=small`（用 Ollama 时默认）会使用更短的提示词、更少的手册条目和固定的回答格式，适合 7B 左右的本地模型。
- 换模型后可运行 `python tools/eval_model.py http://服务器IP:8080` 做自检：10 个标准问题，检查有没有断电提醒、关键排查项，以及会不会编造不存在的代码含义或被“忽略以上规则”这类话带偏。

要增减经验，直接编辑 `families.json`（保存后重启）。需要说明的是：这把我的排查思路写成了规则和清单，能明显提高小模型的下限，但不等于小模型具备同样的判断力；
遇到手册和资料里都没有的疑难问题，仍建议使用能力更强的模型，或联系厂家。

## 管理员知识库（接线、图纸、现场案例）

在服务器 `.env` 里设置 `ADMIN_TOKEN=一串足够长的随机字符`，重启后打开 `http://服务器IP:8080/admin/`，输入令牌登录。
不设置令牌时管理功能整体关闭。

| 可以录入 | 说明 |
|---|---|
| 故障条目 | 手册里没有的代码，或本厂实际的原因和处理办法，查询时排在手册条目前面，标注“现场录入” |
| 接线 / 图纸 | 直接打字（端子号、线号、连接关系），或上传图纸、接线照片；配了能看图的大模型时会自动转写图中文字，转写结果请核对 |
| 现场案例 | 某台设备出过什么故障、怎么处理的；可附照片 |
| 手册 / PDF / 文本 | 上传 PDF 会逐页读取文字，按故障代码检索到具体页；扫描版 PDF 没有文字，只能下载查看 |

查询时，会按故障代码、系列和关键词自动找出相关资料，显示在结果的“本厂资料”里（图纸照片直接显示），
也会交给大模型引用，回答里注明资料标题和页码。接线信息只会照抄资料原文，资料里没有就说没有。

### 把整本手册导入（不只是故障码表）

故障码表整理成了结构化条目（查得准），但手册里的接线、参数说明、调试步骤也很有用。管理页的“官方手册库”可以让**服务器自己**从施耐德官网下载整本 PDF，
逐页读取文字并建立索引（ATV12/312/320/340/600/610/71 的手册链接已预置，点“导入”即可，也可以粘贴其他官方 PDF 链接，如安装手册）：

- 之后出现故障时，除了故障码条目，还会把手册里相关的页（按代码、参数名、现象匹配）一并交给大模型，回答里注明手册名和页码。
- 为安全起见，只允许从施耐德官方域名（download.se.com 等）的 https 链接下载，重定向也只能在这些域名内。
- 需要服务器能访问外网；一本大约 1～3 分钟，同一时间只导入一本；单个文件上限由 `MAX_IMPORT_MB` 控制（默认 200）。
- 手册 PDF 保存在 `local/`（Docker 命名卷），不在 GitHub 仓库里。服务器连不上外网时，可以在别的电脑下载 PDF，再用“新增资料”上传。
- 只检索文字：扫描版 PDF 没有文字，图片里的表格和接线图也读不出来。导入后请用一个已知代码或参数名试查，确认能搜到正确的页；若页面文字是乱码，说明该 PDF 的字体无法提取。

- 数据保存在 `local/` 目录：Docker 用的是命名卷 `local-data`，二进制版在程序旁边的 `local` 文件夹。
- **请定期在管理页“备份/工具”里下载备份 zip**，服务器重装前必须备份。
- 查询页本身不需要密码，但“本厂资料”里的图片和 PDF 知道链接的人都能看到，不要上传不想让厂内其他人看到的内容。

## 部署（Docker）

```bash
git clone https://github.com/fengyeyingxiyang/ai.git && cd ai
cp .env.example .env        # 编辑 .env，选择大模型
docker compose up -d
```

浏览器访问 `http://服务器IP:8080`。

镜像由 GitHub Actions 自动编译：推送到 `main` 后，Actions 会运行测试并把镜像发布到
`ghcr.io/fengyeyingxiyang/ai:latest`（同时支持 amd64 和 arm64）。

- 首次发布后，在 GitHub 的 **Packages → ai → Package settings** 里把可见性改为 Public，服务器才能免登录拉取；
  或者在服务器上先执行 `docker login ghcr.io`。
- 想在服务器本机直接编译：在 `docker-compose.yml` 里把 `image:` 一行注释掉，启用 `build: .`。
- 更新：`docker compose pull && docker compose up -d`。

## 不用 Docker：直接运行的单文件版（Linux / Windows）

每次推送到 `main`，Actions 会同时编译出两个包，在仓库的 **Actions → 最新一次运行 → Artifacts** 下载：

- `fault-assistant-linux-x64`（`.tar.gz`，Debian 11 及以上、Ubuntu 20.04 及以上可用）
- `fault-assistant-windows-x64`（`.zip`，含 `fault-assistant.exe`）

想要永久下载链接，给仓库打一个版本标签即可，Actions 会自动创建 Release 并附上这两个包：

```bash
git tag v1.0.0 && git push origin v1.0.0
```

使用：解压 → 复制 `.env.example` 为 `.env` 并填好大模型配置 → Windows 双击 `fault-assistant.exe`，
Linux 执行 `./fault-assistant` → 按窗口里显示的地址用手机访问。`data/` 文件夹可直接编辑，重启生效。
Windows 首次运行请在防火墙提示里选“允许”，程序没有代码签名，可能出现“未知发布者”提示。

目前只有 x86-64 版本；树莓派等 ARM 设备请用上面的 Docker 方式。

## 选择大模型（编辑 `.env`）

| 方式 | 关键配置 |
|---|---|
| Claude | `LLM_PROVIDER=anthropic`，填 `ANTHROPIC_API_KEY` |
| OpenAI | `LLM_PROVIDER=openai`，填 `OPENAI_API_KEY` |
| 通义千问 | `LLM_PROVIDER=openai`，`OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`，`LLM_MODEL=qwen-vl-max` |
| 本地 Ollama | `LLM_PROVIDER=ollama`，`LLM_MODEL=qwen2.5vl:7b`，`OLLAMA_BASE_URL` 指向 Ollama |

改完 `.env` 后执行 `docker compose up -d` 生效。API Key 只放在服务器的 `.env` 里，不要提交到 GitHub。
纯文字模型请设置 `LLM_VISION=false`，这时照片功能会提示手动输入代码。

## 新增手册 / 新系列

`data/` 下每个 `.psv` 文件是一个系列，直接编辑即可，无需重新编译：

```
# series: ATV320
# title: Schneider Altivar Machine ATV320
# source: ATV320 Programming Manual NVE41295, Diagnostics pp.xxx
# aliases: ATV320, ALTIVAR MACHINE
代码|名称|可能原因|处理办法|复位方式
OCF|Overcurrent|...|...|power
LFF1/LFF2|AI1/AI2 4-20 mA loss|...|...|auto
```

- 同样内容的多个代码用 `/` 连接，会自动拆成多条。
- 复位方式：`power` 需断电重启 · `auto` 可复位/自动重启 · `rsf` 需复位输入 · `hrfc` 需扩展复位 · `self` 原因消除后自动清除，留空表示无。
- 条目里不要出现 `|` 字符。
- 保存后执行 `docker compose restart`。

## 安全说明

- 查询页无密码，适合厂内局域网；管理页需要 `ADMIN_TOKEN`，连续输错 10 次会锁定 5 分钟。管理页走 HTTP 时令牌是明文传输，不要放到公网。放到公网会有人刷你的大模型额度：保留 `RATE_LIMIT_PER_MIN`，
  并在前面加反向代理，同时设置 `TRUST_PROXY=true`。
- 手机浏览器在 HTTP 下不能用网页直接调用摄像头，但“拍照/选图”按钮走系统相机，HTTP 下可正常使用。

## 本地开发

```bash
pip install -r requirements-dev.txt
pytest -q
uvicorn app.main:app --reload --port 8080
```
