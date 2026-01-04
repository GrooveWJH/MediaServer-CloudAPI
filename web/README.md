# Photo Web Module

此目录是可移植的媒体列表渲染模块，可直接拷贝到其他项目（例如 3D 渲染页面）中使用。

## 需要的后端接口

默认 `apiBase` 为 ""，即与页面同域：

- `GET /api/media?since_id=<id>`
- `POST /delete`（form: `record_id`, `object_key`）
- `GET /preview?object_key=<key>`

## 前端接入（推荐）

```html
<link rel="stylesheet" href="/static/media_section.css" />
<section id="media-section"></section>
<script type="module">
  import { initMediaSection } from "/static/media_section.js";
  initMediaSection({ root: "#media-section", apiBase: "" });
</script>
```

如果不使用额外 CSS，可直接复用页面里的 style。

## 结构说明

- `static/media_section.js`：核心渲染逻辑（增量拉取、删除、图片重试）
- `templates/_media_section.html`：模板片段（可选）
- `app.py`：示例 Flask Web（可删）
