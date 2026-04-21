---
name: UI Reverse Engineer
description: 自动化网页 UI/UX 逆向抓取工具。使用 Playwright 自动抓取页面布局、组件样式、交互逻辑，并生成结构化 Markdown 报告。当用户要求：(1) 自动抓取网页 UI (2) 批量分析页面交互流程 (3) 从 URL 生成完整的 UI/UX 文档 时使用此技能。
---

## 依赖环境

1. **Python 3.8+**
2. **Playwright**:
   ```
   pip install playwright
   playwright install chromium
   ```

## 操作流程

### 1. 执行抓取

```bash
python scripts/ui_agent.py <URL> [max_depth]
```

- `URL`: 目标网页地址
- `max_depth`: 最大交互深度（默认 10）

### 2. 登录处理

脚本自动检测登录页面：
- 检测到需要登录时，等待用户在浏览器中手动完成
- 登录成功后保存状态到 `auth_state.json`
- 后续运行自动加载已保存状态

### 3. 自动抓取能力

- **无限滚动处理**：自动执行 3 次滚动以加载懒加载内容
- **弹窗/抽屉检测**：识别 z-index 极高的覆盖层（modal、drawer）
- **交互自动探索**：自动点击可交互元素，记录跳转/弹窗/DOM 变化
- **递归页面探索**：支持多层级页面交互链抓取

### 4. 输出文件

| 文件 | 说明 |
|------|------|
| `ui_analysis_report.json` | 原始结构化数据 |
| `ui_analysis_report.md` | Markdown 报告（参考 UI-Extractor 结构） |
| `screenshot_*.png` | 页面截图 |

## Markdown 输出结构

内容标准格式，包含：

1. **页面基础信息**：网址、标题、布局类型
2. **页面布局结构**：顶部/侧边/主体/底部/弹窗区域
3. **核心元素清单**：按钮、链接等可交互元素表
4. **交互逻辑详解**：点击交互、弹窗交互、DOM 变化
5. **完整操作流程**：业务逻辑链路
6. **页面还原备注**：Design Tokens + 布局特点

## 注意事项

- **隐私**：不记录敏感输入（如密码）
- **性能**：深度过大会增加抓取时间，建议 10-20
- **状态持久化**：首次登录后会自动复用 `auth_state.json`
