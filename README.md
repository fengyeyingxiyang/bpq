# 变频器故障查询（施耐德）

手机浏览器打开即用：输入故障代码，或拍一张变频器面板照片，给出故障说明、可能原因和处理办法。
不需要登录，访问 `http://服务器IP:8080` 即可。

## 工作方式

```
故障代码 / 照片 ──► 大模型读图取代码 ──► 查手册知识库 ──► 大模型按手册条目用中文回答
```

- 回答只依据 `data/` 里整理的手册条目，库里没有的代码会明确说明，不会编造。
- 大模型可选：Claude、OpenAI 兼容接口（OpenAI、通义千问、DeepSeek 等）、本地 Ollama。
- 不配置大模型也能用，只是显示手册英文原文，且不能识别照片。

## 已收录的系列

| 系列 | 条目数 | 来源 |
|---|---|---|
| ATV12 | 43 | ATV12 User Manual BBV28581 |
| ATV61 | 73 | Altivar 61 Programming Manual |
| ATV600（ATV630/650/660/680 等） | 134 | Altivar Process ATV600 Programming Manual EAV64318.11 |

**尚未收录：ATV312、ATV320、ATV340、ATV610、ATV71。** 这些手册的“故障诊断”章节在线抓取时被截断，没有取到。
把对应手册 PDF 放进仓库（或发给开发者），按下面“新增手册”的格式整理即可。
警告码（Warning，如 FFDA、THA）也未收录，目前只有故障码（Error）。

> 条目是对官方手册的精简整理，现场处理请以原版手册为准。

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

- 无密码，适合厂内局域网。放到公网会有人刷你的大模型额度：保留 `RATE_LIMIT_PER_MIN`，
  并在前面加反向代理，同时设置 `TRUST_PROXY=true`。
- 手机浏览器在 HTTP 下不能用网页直接调用摄像头，但“拍照/选图”按钮走系统相机，HTTP 下可正常使用。

## 本地开发

```bash
pip install -r requirements-dev.txt
pytest -q
uvicorn app.main:app --reload --port 8080
```
