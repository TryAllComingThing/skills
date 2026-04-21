import asyncio
import json
import os
import time
import re
from playwright.async_api import async_playwright, expect
from urllib.parse import urljoin, urlparse


class AutoUXAgent:
    def __init__(self, start_url, auth_file="auth_state.json", max_depth=10):
        self.start_url = start_url
        self.auth_file = auth_file
        self.max_depth = max_depth  # 最大交互深度
        self.results = {
            "pages": {},
            "interactions": []
        }
        self.visited_urls = set()
        self.visited_elements = set()  # 防止重复点击
        self.context = None
        self.browser = None
        self.page = None

    async def setup(self, playwright):
        """初始化浏览器"""
        for channel in ['chromium']:
            try:
                self.browser = await playwright.chromium.launch(headless=False, channel=channel)
                print(f"[+] 使用系统浏览器: {channel}")
                break
            except Exception as e:
                continue
        else:
            # 如果系统浏览器都不可用，尝试默认chromium
            self.browser = await playwright.chromium.launch(headless=False)

        context_args = {}
        if os.path.exists(self.auth_file):
            context_args["storage_state"] = self.auth_file

        self.context = await self.browser.new_context(
            **context_args,
            viewport={'width': 1280, 'height': 800},
            ignore_https_errors=True  # 忽略自签名证书错误
        )
        self.page = await self.context.new_page()

    async def is_login_required(self):
        """检测是否需要登录"""
        login_keywords = ["login", "signin", "登录", "注册", "auth", "signin"]
        current_url = self.page.url.lower()
        has_password_field = await self.page.query_selector('input[type="password"]')
        has_login_form = await self.page.query_selector('form')

        return (any(k in current_url for k in login_keywords) or
                has_password_field or
                (has_login_form and "password" in current_url))

    async def wait_for_user_login(self):
        """等待用户手动登录 - 等待所有字段填写完成、勾选确认并点击登录按钮后才认为登录完成"""
        print("[!] 检测到需要登录。请在弹出的浏览器中操作。")
        print("[!] 请填写：用户名、密码、验证码，勾选'阅读已知'，然后点击登录按钮。")
        print("[!] 脚本将自动检测登录是否成功...")

        # 记录原始URL
        original_url = self.page.url

        # 等待登录成功 - 检测以下任一条件满足：
        # 1. URL变化且不再包含login
        # 2. 登录表单消失
        # 3. 出现用户信息元素
        # 4. 登录按钮状态变化（不可见/禁用）
        login_success = False

        for attempt in range(120):  # 最多等待2分钟
            await asyncio.sleep(1)

            try:
                current_url = self.page.url
            except Exception:
                # 页面正在导航，这通常是登录成功的信号
                print("[+] 页面正在跳转，登录可能成功")
                login_success = True
                break

            # 检查1: URL变化且不再包含login
            if current_url != original_url and "login" not in current_url.lower():
                print("[+] 检测到页面跳转，登录成功")
                login_success = True
                break

            # 检查2: 登录表单是否消失（密码字段不存在说明可能已登录）
            try:
                password_field = await self.page.query_selector('input[type="password"]')
                if not password_field:
                    print("[+] 登录表单已消失，登录成功")
                    login_success = True
                    break
            except Exception:
                # 页面导航中
                print("[+] 页面跳转中，登录成功")
                login_success = True
                break

            # 检查3: 验证码输入完成（如果有验证码字段且已填写）
            try:
                captcha_field = await self.page.query_selector('input[placeholder*="验证码"], input[id*="code"], input[name*="code"], input[name*="captcha"]')
                if captcha_field:
                    captcha_value = await captcha_field.input_value()
                    if not captcha_value and attempt > 5:
                        # 等待用户输入验证码
                        continue
            except Exception:
                pass

            # 检查4: 检查阅读/同意复选框是否已勾选
            try:
                checkbox = await self.page.query_selector('input[type="checkbox"]')
                if checkbox:
                    is_checked = await checkbox.is_checked()
                    if not is_checked and attempt > 10:
                        # 提示用户勾选
                        if attempt % 10 == 0:
                            print("[*] 等待勾选'阅读已知'...")
            except Exception:
                pass

        if not login_success:
            print("[!] 等待超时，尝试保存当前状态...")

        # 等待页面加载完成
        try:
            await self.page.wait_for_load_state("networkidle", timeout=10000)
        except:
            pass

        # 保存登录状态
        await self.context.storage_state(path=self.auth_file)
        print("[+] 登录状态已保存。")

        # 保存登录状态
        await self.context.storage_state(path=self.auth_file)
        print("[+] 登录状态已保存。")

    async def scroll_to_load_all(self):
        """滚动页面以加载所有懒加载内容"""
        print("[*] 滚动加载页面...")

        # 滚动 3 次，每次等待加载
        for i in range(3):
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)
            await self.page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.5)

        # 尝试点击 "加载更多" 按钮
        load_more_buttons = await self.page.query_selector_all(
            "button:has-text('加载更多'), button:has-text('Load more'), "
            "[class*='load'], [class*='more'], a:has-text('加载更多')"
        )
        for btn in load_more_buttons[:3]:
            try:
                await btn.click()
                await asyncio.sleep(1)
            except:
                pass

    async def scroll_explore_all_directions(self):
        """多方向滚动探索，确保所有元素可见并展开折叠内容"""
        print("[*] 多方向滚动探索...")

        # 获取页面可滚动尺寸
        scroll_info = await self.page.evaluate("""
            () => ({
                width: document.documentElement.scrollWidth,
                height: document.documentElement.scrollHeight,
                viewWidth: window.innerWidth,
                viewHeight: window.innerHeight
            })
        """)
        scroll_width = scroll_info.get("width", 0)
        scroll_height = scroll_info.get("height", 0)

        # 步骤1: 垂直滚动探索 (上→下→上)
        print("[*] 垂直滚动探索...")
        await self.page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.5)

        # 向下滚动并加载
        for y in range(0, int(scroll_height), 500):
            await self.page.evaluate(f"window.scrollTo(0, {y})")
            await asyncio.sleep(0.3)

        await self.page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.5)

        # 步骤2: 水平滚动探索 (左→右→左)
        print("[*] 水平滚动探索...")
        if scroll_width > 0:
            for x in range(0, int(scroll_width), 500):
                await self.page.evaluate(f"window.scrollTo({x}, 0)")
                await asyncio.sleep(0.3)

            await self.page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.5)

        # 步骤3: 展开所有折叠面板/Dropdown
        print("[*] 展开折叠内容...")
        await self.expand_all_foldable_content()

        # 步骤4: 回到顶部
        await self.page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.5)

    async def expand_all_foldable_content(self):
        """展开所有可折叠内容（手风琴、下拉菜单等）"""
        # 展开所有下拉菜单/select
        dropdowns = await self.page.query_selector_all(
            "select, [class*='dropdown'], [class*='select'], "
            "[role='combobox'], [aria-expanded='false']"
        )
        for dd in dropdowns[:20]:
            try:
                if await dd.is_visible():
                    await dd.click()
                    await asyncio.sleep(0.3)
            except:
                pass

        # 展开所有折叠面板/accordion
        collapse_toggles = await self.page.query_selector_all(
            "[class*='collapse'], [class*='accordion'], "
            "[data-toggle*='collapse'], [aria-expanded='false'], "
            "button:has-text('展开'), button:has-text('更多'), a:has-text('展开')"
        )
        for toggle in collapse_toggles[:20]:
            try:
                if await toggle.is_visible():
                    await toggle.click()
                    await asyncio.sleep(0.3)
            except:
                pass

        # 点击可能展开更多内容的"更多"按钮
        more_buttons = await self.page.query_selector_all(
            "button:has-text('更多'), a:has-text('更多'), "
            "[class*='expand'], [class*='toggle']"
        )
        for btn in more_buttons[:15]:
            try:
                if await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.5)
            except:
                pass

    async def analyze_navigation_structure(self):
        """分析页面导航结构，提取功能模块"""
        print("[*] 分析导航结构...")

        navigation = {
            "sidebar_menus": [],
            "top_menus": [],
            "breadcrumb": [],
            "tabs": [],
            "modules": []
        }

        # 1. 提取左侧/侧边栏菜单
        sidebar_selectors = [
            "[class*='sidebar'], [class*='aside'], [class*='menu'], "
            "[class*='nav'], [id*='sidebar'], [id*='menu'], "
            "[role='navigation'], nav, aside"
        ]
        sidebar_elements = []
        for selector in sidebar_selectors:
            try:
                elements = await self.page.query_selector_all(selector)
                sidebar_elements.extend(elements)
            except:
                pass

        # 从侧边栏提取菜单项
        for sidebar in sidebar_elements[:5]:
            try:
                if not await sidebar.is_visible():
                    continue

                # 查找菜单项链接
                menu_links = await sidebar.query_selector_all("a, button, [role='menuitem']")
                for link in menu_links[:30]:
                    try:
                        text = (await link.inner_text()).strip()
                        href = await link.get_attribute("href")
                        if text and len(text) > 0 and len(text) < 50:
                            navigation["sidebar_menus"].append({
                                "text": text,
                                "href": href,
                                "type": "menu_item"
                            })
                    except:
                        continue
            except:
                continue

        # 2. 提取顶部导航
        topnav_selectors = [
            "[class*='header'], [class*='topbar'], [class*='navbar'], "
            "[class*='nav'], [id*='header'], [id*='navbar'], "
            "header, [role='banner']"
        ]
        for selector in topnav_selectors:
            try:
                topnav = await self.page.query_selector(selector)
                if topnav and await topnav.is_visible():
                    links = await topnav.query_selector_all("a, button")
                    for link in links[:20]:
                        try:
                            text = (await link.inner_text()).strip()
                            href = await link.get_attribute("href")
                            if text and len(text) > 0 and len(text) < 30:
                                navigation["top_menus"].append({
                                    "text": text,
                                    "href": href
                                })
                        except:
                            continue
                    break
            except:
                continue

        # 3. 提取面包屑导航
        breadcrumb = await self.page.query_selector_all(
            "[class*='breadcrumb'], [class*='path'], [aria-label='breadcrumb'], "
            ".breadcrumb, .bread-crumb"
        )
        for bc in breadcrumb[:3]:
            try:
                items = await bc.query_selector_all("a, span")
                for item in items[:10]:
                    text = (await item.inner_text()).strip()
                    if text:
                        navigation["breadcrumb"].append(text)
            except:
                continue

        # 4. 提取 Tab 切换
        tabs = await self.page.query_selector_all(
            "[class*='tab'], [role='tab'], .tabs, .tab-group"
        )
        for tab in tabs[:5]:
            try:
                tab_items = await tab.query_selector_all(
                    "[role='tab'], button, a, .tab-item"
                )
                for item in tab_items[:15]:
                    text = (await item.inner_text()).strip()
                    if text:
                        navigation["tabs"].append(text)
            except:
                continue

        # 5. 从 URL 推断模块
        parsed_url = urlparse(self.page.url)
        path_parts = [p for p in parsed_url.path.split('/') if p]
        navigation["modules"] = path_parts[:5]  # 保留前5层路径

        # 保存导航结构
        self.results["navigation"] = navigation
        print(f"[+] 导航结构: {len(navigation['sidebar_menus'])} 个侧边栏菜单, "
              f"{len(navigation['top_menus'])} 个顶部菜单")

        return navigation

    async def analyze_forms_and_operations(self):
        """分析表单结构和操作，推断业务操作类型"""
        print("[*] 分析表单和操作...")

        forms_analysis = {
            "forms": [],
            "operations": [],  # 操作序列: button + form context
            "data_fields": []
        }

        # 1. 提取所有表单
        forms = await self.page.query_selector_all("form")
        for form in forms[:10]:
            try:
                form_info = {
                    "id": await form.get_attribute("id"),
                    "action": await form.get_attribute("action"),
                    "method": await form.get_attribute("method"),
                    "fields": []
                }

                # 提取表单字段
                inputs = await form.query_selector_all("input, select, textarea")
                for inp in inputs[:30]:
                    try:
                        field_type = await inp.get_attribute("type") or "text"
                        field_name = await inp.get_attribute("name") or ""
                        field_id = await inp.get_attribute("id") or ""
                        placeholder = await inp.get_attribute("placeholder") or ""

                        # 查找字段标签
                        label_text = ""
                        label_el = await inp.query_selector("label")
                        if label_el:
                            label_text = (await label_el.inner_text()).strip()

                        form_info["fields"].append({
                            "type": field_type,
                            "name": field_name,
                            "id": field_id,
                            "label": label_text,
                            "placeholder": placeholder
                        })

                        forms_analysis["data_fields"].append({
                            "name": field_name,
                            "label": label_text,
                            "type": field_type
                        })
                    except:
                        continue

                forms_analysis["forms"].append(form_info)
            except:
                continue

        # 2. 提取操作按钮并关联表单上下文
        buttons = await self.page.query_selector_all(
            "button, input[type='submit'], a[class*='btn'], [role='button']"
        )

        for btn in buttons[:30]:
            try:
                btn_text = (await btn.inner_text()).strip()
                if not btn_text or len(btn_text) > 20:
                    continue

                # 分类业务动作
                action_type = self._classify_business_action(btn_text)

                # 查找相邻的表单
                form_context = None
                try:
                    # 尝试找父级表单
                    parent_form = await btn.query_selector("form")
                    if parent_form:
                        form_context = "in_form"
                    else:
                        # 查找附近的上一个表单
                        form_context = "nearby_form"
                except:
                    form_context = "standalone"

                forms_analysis["operations"].append({
                    "button_text": btn_text,
                    "action_type": action_type,
                    "context": form_context,
                    "description": self._generate_operation_description(btn_text, action_type)
                })
            except:
                continue

        # 保存表单分析结果
        self.results["forms_analysis"] = forms_analysis
        print(f"[+] 表单分析: {len(forms_analysis['forms'])} 个表单, "
              f"{len(forms_analysis['operations'])} 个操作")

        return forms_analysis

    def _generate_operation_description(self, button_text, action_type):
        """生成操作描述"""
        descriptions = {
            "create": f"创建新记录（点击 {button_text}）",
            "update": f"更新记录（点击 {button_text}）",
            "delete": f"删除记录（点击 {button_text}）",
            "authorize": f"权限管理（点击 {button_text}）",
            "query": f"查询数据（点击 {button_text}）",
            "import_export": f"数据导入导出（点击 {button_text}）",
            "submit": f"提交表单（点击 {button_text}）",
            "approve": f"审批操作（点击 {button_text}）",
            "other": f"点击 {button_text}"
        }
        return descriptions.get(action_type, descriptions["other"])

    async def detect_modals_and_drawers(self):
        """检测弹窗和抽屉"""
        modals = []

        # 查找常见弹窗选择器
        modal_selectors = [
            "[role='dialog']", "[role='modal']", ".modal", ".drawer",
            "[class*='modal']", "[class*='dialog']", "[class*='drawer']",
            "[class*='popup']", "[class*='overlay']"
        ]

        for selector in modal_selectors:
            elements = await self.page.query_selector_all(selector)
            for el in elements:
                try:
                    is_visible = await el.is_visible()
                    if is_visible:
                        box = await el.bounding_box()
                        if box and box['width'] > 100 and box['height'] > 100:
                            text = (await el.inner_text())[:100]
                            modals.append({
                                "type": "modal" if box['width'] < 1000 else "drawer",
                                "text": text,
                                "rect": box
                            })
                except:
                    continue

        return modals

    async def capture_current_state(self, state_name):
        """抓取当前页面状态"""
        print(f"[*] 抓取状态: {state_name}")

        # 检测弹窗
        modals = await self.detect_modals_and_drawers()

        # 注入 JS 提取布局数据
        layout_data = await self.page.evaluate("""
            () => {
                const getLayout = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);

                    const isComponent = (
                        ['BUTTON', 'INPUT', 'SELECT', 'NAV', 'ASIDE', 'HEADER',
                         'SECTION', 'FOOTER', 'MAIN', 'ARTICLE', 'FORM', 'TABLE'].includes(el.tagName) ||
                        el.classList.contains('card') || el.classList.contains('menu') ||
                        el.getAttribute('role') === 'button' || el.getAttribute('role') === 'navigation' ||
                        (rect.width > 50 && rect.height > 30 && style.position === 'fixed')
                    );

                    if (!isComponent && el.children.length > 8) return null;
                    if (rect.width < 5 || rect.height < 5) return null;

                    // 处理 className 可能是字符串或 SVGAnimatedString 的情况
                    const className = typeof el.className === 'string' ? el.className :
                                      el.className?.baseVal || '';

                    return {
                        tag: el.tagName,
                        text: el.innerText?.slice(0, 50)?.replace(/\\s+/g, ' '),
                        id: el.id,
                        class: className?.slice(0, 100),
                        role: el.getAttribute('role'),
                        rect: { x: Math.round(rect.x), y: Math.round(rect.y),
                                w: Math.round(rect.width), h: Math.round(rect.height) },
                        styles: {
                            color: style.color,
                            bg: style.backgroundColor,
                            borderRadius: style.borderRadius,
                            fontSize: style.fontSize,
                            fontWeight: style.fontWeight,
                            padding: style.padding,
                            margin: style.margin,
                            position: style.position,
                            display: style.display,
                            flexDirection: style.flexDirection,
                            zIndex: style.zIndex
                        },
                        isVisible: rect.width > 0 && rect.height > 0
                    };
                };

                const all = document.querySelectorAll('body *');
                return Array.from(all)
                    .map(getLayout)
                    .filter(item => item && item.isVisible)
                    .slice(0, 200);  // 限制数量
            }
        """)

        # 获取页面基本信息
        title = await self.page.title()

        # 分析布局结构
        layout_structure = await self.analyze_layout(layout_data)

        # 提取可交互元素
        interactive_elements = await self.extract_interactive_elements()

        page_key = self.page.url
        self.results["pages"][page_key] = {
            "state": state_name,
            "url": self.page.url,
            "title": title,
            "elements": layout_data,
            "modals": modals,
            "layout": layout_structure,
            "interactive": interactive_elements
        }

        # 截图
        screenshot_name = f"screenshot_{int(time.time())}_{state_name.replace(' ', '_')}.png"
        await self.page.screenshot(path=screenshot_name, full_page=True)

        return modals

    async def analyze_layout(self, elements):
        """分析页面布局结构"""
        layout = {
            "header": None,
            "sidebar": None,
            "main": None,
            "footer": None
        }

        for el in elements:
            if not el or not el.get("rect"):
                continue
            rect = el["rect"]
            tag = el.get("tag", "").upper()

            # 顶部区域
            if tag in ["HEADER", "NAV"] and rect["y"] < 100:
                layout["header"] = {"height": rect["h"], "width": rect["w"]}

            # 侧边栏
            if (tag in ["ASIDE", "NAV"] or "sidebar" in el.get("class", "").lower()) and rect["x"] < 300:
                layout["sidebar"] = {"x": rect["x"], "height": rect["h"], "width": rect["w"]}

            # 主体区域
            if tag in ["MAIN", "SECTION"] and rect["y"] > 50 and rect["h"] > 300:
                layout["main"] = {"height": rect["h"], "width": rect["w"]}

            # 底部
            if tag == "FOOTER":
                layout["footer"] = {"height": rect["h"], "width": rect["w"]}

        return layout

    async def extract_all_clickable_elements(self):
        """提取所有可点击元素 - 不依赖关键词"""
        all_elements = []

        # 1. 标准可交互元素
        selectors = [
            "button", "a", "input[type='button']", "input[type='submit']",
            "[role='button']", "[role='link']", "[role='tab']",
            "[onclick]", "[oncontextmenu]", "[ondblclick']",
            "summary",  # details/summary 折叠元素
            ".clickable", "[data-clickable='true']"
        ]

        for selector in selectors:
            try:
                elements = await self.page.query_selector_all(selector)
                for el in elements:
                    try:
                        if not await el.is_visible():
                            continue
                        tag = await el.evaluate("el => el.tagName.toLowerCase()")
                        text = (await el.inner_text()).strip()[:50]
                        # 如果没有文本，尝试获取 aria-label 或 title
                        if not text:
                            text = await el.get_attribute("aria-label") or await el.get_attribute("title") or ""
                            text = text.strip()[:50]
                        # 跳过空白元素
                        if not text and tag not in ["img", "svg", "icon"]:
                            continue
                        box = await el.bounding_box()
                        all_elements.append({
                            "text": text,
                            "tag": tag,
                            "selector": selector,
                            "id": await el.get_attribute("id"),
                            "class": await el.get_attribute("class"),
                            "href": await el.get_attribute("href"),
                            "role": await el.get_attribute("role"),
                            "aria_label": await el.get_attribute("aria-label"),
                            "data_action": await el.get_attribute("data-action"),
                            "position": box if box else None
                        })
                    except:
                        continue
            except:
                continue

        # 2. 提取 Tab 元素（ul/li 结构）
        try:
            tab_lists = await self.page.query_selector_all("[role='tablist'], .nav-tabs, .tabs, .ant-tabs, .el-tabs")
            for tab_list in tab_lists:
                try:
                    tabs = await tab_list.query_selector_all("[role='tab'], .nav-item, .ant-tabs-tab, .el-tabs-item")
                    for tab in tabs:
                        try:
                            if not await tab.is_visible():
                                continue
                            text = (await tab.inner_text()).strip()[:30]
                            if not text:
                                continue
                            box = await tab.bounding_box()
                            all_elements.append({
                                "text": f"[Tab] {text}",
                                "tag": "tab",
                                "selector": "[role='tab']",
                                "id": await tab.get_attribute("id"),
                                "role": "tab",
                                "position": box if box else None
                            })
                        except:
                            continue
                except:
                    continue
        except:
            pass

        # 3. 提取下拉菜单项
        try:
            dropdown_items = await self.page.query_selector_all(
                ".dropdown-item, .ant-dropdown-menu-item, .el-dropdown-menu__item, "
                "[role='menuitem'], .menu-item, .nav-dropdown-item"
            )
            for item in dropdown_items[:20]:
                try:
                    if not await item.is_visible():
                        continue
                    text = (await item.inner_text()).strip()[:30]
                    if not text:
                        continue
                    box = await item.bounding_box()
                    all_elements.append({
                        "text": f"[Menu] {text}",
                        "tag": "menuitem",
                        "selector": ".dropdown-item",
                        "role": "menuitem",
                        "position": box if box else None
                    })
                except:
                    continue
        except:
            pass

        # 4. 提取图标按钮（无文本但可点击）
        try:
            icon_buttons = await self.page.query_selector_all(
                ".icon-btn, .anticon, .el-icon, [aria-label], button:empty, "
                "button:has(img), a:has(img), [class*='icon']:not(:has-text())"
            )
            for btn in icon_buttons[:20]:
                try:
                    if not await btn.is_visible():
                        continue
                    aria_label = await btn.get_attribute("aria-label")
                    title = await btn.get_attribute("title")
                    text = aria_label or title or ""
                    if not text:
                        continue
                    box = await btn.bounding_box()
                    all_elements.append({
                        "text": f"[Icon] {text}",
                        "tag": await btn.evaluate("el => el.tagName.toLowerCase()"),
                        "selector": "icon-button",
                        "aria_label": aria_label,
                        "title": title,
                        "position": box if box else None
                    })
                except:
                    continue
        except:
            pass

        # 去重
        seen = set()
        unique_elements = []
        for el in all_elements:
            key = f"{el.get('text', '')}_{el.get('tag', '')}"
            if key not in seen:
                seen.add(key)
                unique_elements.append(el)

        return unique_elements

    async def extract_interactive_elements(self):
        """提取所有可交互元素（兼容旧接口）"""
        return await self.extract_all_clickable_elements()

    async def auto_explore(self, depth=0):
        """自动探索页面交互 - 不依赖关键词"""
        if depth >= self.max_depth:
            return

        current_url = self.page.url
        await asyncio.sleep(1)

        # 获取所有可点击元素
        all_elements = await self.extract_all_clickable_elements()
        print(f"[*] 发现 {len(all_elements)} 个可点击元素")

        # 跳过明显无关的元素
        skip_patterns = ["cookie", "accept", "close", "skip", "cancel"]

        for el_info in all_elements:
            text = el_info.get("text", "").strip()
            if not text:
                continue

            # 跳过无关元素
            if any(p.lower() in text.lower() for p in skip_patterns):
                continue

            # 使用元素标识作为去重键
            element_key = f"{el_info.get('tag', '')}_{el_info.get('text', '')[:20]}"
            if element_key in self.visited_elements:
                continue
            self.visited_elements.add(element_key)

            try:
                print(f"[->] 点击: {text}")

                pre_url = self.page.url
                pre_modals = await self.detect_modals_and_drawers()

                # 尝试点击
                clicked = await self._smart_click(el_info)

                await asyncio.sleep(1.5)

                post_url = self.page.url
                post_modals = await self.detect_modals_and_drawers()

                # 记录交互
                interaction = {
                    "from": text,
                    "tag": el_info.get("tag", ""),
                    "action": "click",
                    "pre_url": pre_url,
                    "post_url": post_url,
                    "result": "",
                    "clicked": clicked
                }

                if pre_url != post_url:
                    interaction["result"] = f"跳转: {post_url}"
                    print(f"[+] 页面跳转")
                    if post_url not in self.visited_urls:
                        self.visited_urls.add(post_url)
                        self.results["interactions"].append(interaction)
                        await self.capture_current_state(f"page_{len(self.visited_urls)}")
                        await self.auto_explore(depth + 1)
                        await self.page.go_back()
                        await asyncio.sleep(1)
                elif post_modals:
                    interaction["result"] = f"弹窗: {len(post_modals)} 个"
                    print(f"[+] 触发弹窗")
                    self.results["interactions"].append(interaction)
                    await self.capture_current_state(f"modal_{text[:10]}")
                    await self.page.keyboard.press("Escape")
                    await asyncio.sleep(0.5)
                elif clicked:
                    interaction["result"] = "DOM变化"
                    print(f"[+] DOM变化")
                    self.results["interactions"].append(interaction)

            except Exception as e:
                print(f"[!] 点击出错: {text} - {str(e)[:40]}")
                continue

    async def _smart_click(self, el_info):
        """智能点击 - 多种策略尝试点击元素"""
        text = el_info.get("text", "")
        tag = el_info.get("tag", "")
        element_id = el_info.get("id")
        role = el_info.get("role")
        aria_label = el_info.get("aria_label")

        # 策略1: 如果有 id，使用 id 选择
        if element_id:
            try:
                el = await self.page.query_selector(f"#{element_id}")
                if el and await el.is_visible():
                    await el.click()
                    return True
            except:
                pass

        # 策略2: 使用 role 属性
        if role:
            try:
                locator = self.page.locator(f"[role='{role}']")
                count = await locator.count()
                for i in range(min(count, 3)):
                    el = locator.nth(i)
                    if await el.is_visible():
                        await el.click()
                        return True
            except:
                pass

        # 策略3: 使用 aria-label
        if aria_label:
            try:
                el = await self.page.query_selector(f"[aria-label='{aria_label}']")
                if el and await el.is_visible():
                    await el.click()
                    return True
            except:
                pass

        # 策略4: 使用文本匹配 (处理 [Tab], [Menu], [Icon] 前缀)
        clean_text = text.replace("[Tab]", "").replace("[Menu]", "").replace("[Icon]", "").strip()
        if clean_text:
            try:
                # 尝试多种选择器
                for selector in [
                    f"button:has-text('{clean_text}')",
                    f"a:has-text('{clean_text}')",
                    f"[role='button']:has-text('{clean_text}')",
                    f"[role='tab']:has-text('{clean_text}')"
                ]:
                    try:
                        locator = self.page.locator(selector)
                        count = await locator.count()
                        if count > 0:
                            for i in range(count):
                                el = locator.nth(i)
                                if await el.is_visible():
                                    await el.click()
                                    return True
                    except:
                        continue
            except:
                pass

        # 策略5: 使用 XPath 文本匹配
        if clean_text:
            try:
                xpath = f"//*[contains(text(), '{clean_text}')]"
                elements = await self.page.query_selector_all(f"xpath={xpath}")
                for el in elements[:3]:
                    try:
                        if await el.is_visible():
                            await el.click()
                            return True
                    except:
                        continue
            except:
                pass

        return False

    def _classify_business_action(self, text):
        """分类业务动作"""
        if any(k in text for k in ["新增", "添加", "创建", "新建"]):
            return "create"
        elif any(k in text for k in ["修改", "编辑", "更新"]):
            return "update"
        elif any(k in text for k in ["删除", "移除"]):
            return "delete"
        elif any(k in text for k in ["授权", "权限", "分配"]):
            return "authorize"
        elif any(k in text for k in ["查询", "搜索", "查找"]):
            return "query"
        elif any(k in text for k in ["导入", "导出", "下载"]):
            return "import_export"
        elif any(k in text for k in ["提交", "确认", "确定"]):
            return "submit"
        elif any(k in text for k in ["审核", "审批", "通过", "拒绝"]):
            return "approve"
        else:
            return "other"

    def generate_markdown(self):
        """生成 Markdown 报告"""
        pages = self.results["pages"]
        interactions = self.results["interactions"]

        md = []
        md.append("# 页面UI/UX解析报告\n")

        # 一、页面基础信息
        md.append("## 一、页面基础信息\n")
        if pages:
            first_page = list(pages.values())[0]
            md.append(f"- 页面网址：{first_page.get('url', '')}\n")
            md.append(f"- 页面标题：{first_page.get('title', '')}\n")
            md.append(f"- 整体布局：")
            layout = first_page.get("layout", {})
            if layout.get("header"):
                md.append("含顶部 Header")
            if layout.get("sidebar"):
                md.append("含侧边栏")
            if layout.get("main"):
                md.append("主体内容区")
            md.append("\n")
            md.append(f"- 页面尺寸：1280 x 800\n")

        # 二、页面布局结构
        md.append("\n## 二、页面布局结构（层级划分）\n")
        if pages:
            for url, page_data in pages.items():
                layout = page_data.get("layout", {})
                md.append(f"### {page_data.get('state', '页面')}\n")
                md.append(f"- 网址：{url}\n")

                if layout.get("header"):
                    md.append(f"- 顶部区域：高度约 {layout['header']['height']}px\n")
                if layout.get("sidebar"):
                    md.append(f"- 侧边区域：宽度约 {layout['sidebar']['width']}px\n")
                if layout.get("main"):
                    md.append(f"- 主体内容区：高度约 {layout['main']['height']}px\n")
                if layout.get("footer"):
                    md.append(f"- 底部区域：高度约 {layout['footer']['height']}px\n")

                modals = page_data.get("modals", [])
                if modals:
                    md.append(f"- 弹窗/抽屉：检测到 {len(modals)} 个\n")
                md.append("\n")

        # 三、核心元素清单
        md.append("## 三、核心元素清单\n")
        md.append("| 元素类型 | 元素名称 | 位置 | 状态 |\n")
        md.append("| ---- | ---- | ---- | ---- |\n")

        if pages:
            first_page = list(pages.values())[0]
            interactive = first_page.get("interactive", [])

            # 按钮
            buttons = [i for i in interactive if i.get("tag", "").upper() == "BUTTON"]
            for btn in buttons[:5]:
                pos = btn.get("position", {})
                pos_str = f"{pos.get('x', 0)},{pos.get('y', 0)}" if pos else ""
                md.append(f"| 按钮 | {btn.get('text', '')} | {pos_str} | visible |\n")

            # 链接
            links = [i for i in interactive if i.get("tag", "").upper() == "A"]
            for link in links[:5]:
                pos = link.get("position", {})
                pos_str = f"{pos.get('x', 0)},{pos.get('y', 0)}" if pos else ""
                md.append(f"| 链接 | {link.get('text', '')} | {pos_str} | visible |\n")

        # 四、交互逻辑详解
        md.append("\n## 四、交互逻辑详解\n")

        # 分组交互
        clicks = [i for i in interactions if i.get("action") == "click"]

        jumps = [i for i in clicks if "跳转" in i.get("result", "")]
        modals = [i for i in clicks if "弹窗" in i.get("result", "")]
        doms = [i for i in clicks if "DOM" in i.get("result", "")]

        md.append("### 1. 基础交互\n")
        md.append("- 页面加载自动触发\n")
        md.append("- 滚动加载更多内容（3次滚动）\n\n")

        md.append("### 2. 点击交互\n")
        for i in jumps[:5]:
            md.append(f"- 点击「{i.get('from', '')}」→ {i.get('result', '')}\n")

        md.append("\n### 3. 弹窗/抽屉交互\n")
        for i in modals[:5]:
            md.append(f"- 点击「{i.get('from', '')}」→ {i.get('result', '')}\n")

        md.append("\n### 4. DOM变化交互\n")
        for i in doms[:5]:
            md.append(f"- 点击「{i.get('from', '')}」→ {i.get('result', '')}\n")

        # 五、完整操作流程
        md.append("\n## 五、完整操作流程（业务逻辑）\n")
        for idx, i in enumerate(interactions[:10], 1):
            md.append(f"{idx}. 点击「{i.get('from', '')}」→ {i.get('result', '')}\n")

        # 六、页面还原备注
        md.append("\n## 六、页面还原备注\n")
        md.append("### 布局特点\n")
        if layout:
            if layout.get("header"):
                md.append("- 顶部 Header 固定高度\n")
            if layout.get("sidebar"):
                md.append("- 左侧 Sidebar 固定宽度\n")
            if layout.get("main"):
                md.append("- 主体内容自适应\n")

        md.append("\n### 交互注意事项\n")
        md.append("- 弹窗/抽屉需检测 z-index\n")
        md.append("- 表单提交需等待网络请求完成\n")
        md.append("- 页面跳转需等待新页面加载完成\n")

        return "".join(md)

    # ========== LLM 辅助分析相关函数 ==========

    async def capture_page_for_llm(self):
        """捕获页面截图和HTML供LLM分析"""
        print("[*] 捕获页面信息...")

        # 1. 截图
        screenshot_bytes = await self.page.screenshot(full_page=True)

        # 保存截图
        import base64
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_file = f"screenshot_{timestamp}.png"
        with open(screenshot_file, "wb") as f:
            f.write(screenshot_bytes)
        print(f"[+] 截图已保存: {screenshot_file}")

        # 2. 提取简化版 HTML（去除脚本和样式）
        html_content = await self.page.evaluate("""
            () => {
                // 克隆文档
                const clone = document.documentElement.cloneNode(true);

                // 移除脚本和样式
                clone.querySelectorAll('script, style, noscript').forEach(el => el.remove());

                // 简化属性
                clone.querySelectorAll('*').forEach(el => {
                    // 保留关键属性
                    const keepAttrs = ['type', 'name', 'id', 'class', 'href', 'src', 'role', 'aria-label', 'placeholder'];
                    const attrs = Array.from(el.attributes);
                    attrs.forEach(attr => {
                        if (!keepAttrs.includes(attr.name)) {
                            el.removeAttribute(attr.name);
                        }
                    });
                });

                return clone.outerHTML.slice(0, 50000); // 限制大小
            }
        """)

        return {
            "screenshot_file": screenshot_file,
            "html_content": html_content,
            "url": self.page.url,
            "title": await self.page.title()
        }

    async def analyze_with_llm(self, page_data):
        """调用阿里云百炼LLM分析页面结构和业务逻辑"""
        import os
        import re

        # 检测 API Key
        api_key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("[!] 未设置 DASHSCOPE_API_KEY 环境变量")
            print("[!] 请设置: set DASHSCOPE_API_KEY=sk-您的密钥")
            return None

        # 构建提示词
        prompt = f"""请分析以下网页截图和HTML代码，回答以下问题：

1. **页面类型**: 这个页面是什么类型的页面？（如：列表页、详情页、表单页、登录页等）

2. **主要功能模块**: 页面包含哪些主要功能区域？请描述每个区域的作用。

3. **业务按钮**: 找出所有业务相关的按钮/链接，并说明其业务含义：
   - 新增/创建按钮
   - 编辑/修改按钮
   - 删除按钮
   - 查询/搜索按钮
   - 导入/导出按钮
   - 提交/确认按钮
   - 其他按钮

4. **数据表单**: 页面上有哪些输入字段？请列出字段名和类型。

5. **操作流程**: 用户在这个页面上可以执行哪些操作？请按优先级排序。

6. **弹窗/交互**: 页面有哪些交互元素？（如下拉菜单、折叠面板、弹窗等）

请用JSON格式输出，格式如下：
```json
{{
  "page_type": "页面类型",
  "function_modules": ["模块1", "模块2", ...],
  "business_buttons": [
    {{"text": "按钮文字", "action": "create/update/delete/query/...", "description": "业务描述"}}
  ],
  "form_fields": [
    {{"name": "字段名", "type": "text/select/checkbox/...", "label": "显示标签"}}
  ],
  "operations": ["操作1", "操作2", ...],
  "interactions": ["下拉菜单", "折叠面板", ...]
}}
```

截图文件: {page_data['screenshot_file']}
页面URL: {page_data['url']}
页面标题: {page_data['title']}

HTML代码片段（前5000字符）:
{page_data['html_content'][:5000]}"""

        print("[*] 调用阿里云百炼 qwen-plus 分析页面...")

        # 调用阿里云百炼 API
        response_text = self._call_dashscope_api(prompt)

        if not response_text:
            return None

        # 尝试提取JSON
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            analysis_result = json.loads(json_match.group())
            print(f"[+] LLM 分析完成: {len(analysis_result.get('business_buttons', []))} 个业务按钮")
            return analysis_result
        else:
            print("[!] 无法解析LLM响应为JSON")
            return {"raw_response": response_text}

    def _call_dashscope_api(self, prompt):
        """调用阿里云百炼 API（OpenAI 兼容格式）"""
        try:
            import os
            from openai import OpenAI

            api_key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("OPENAI_API_KEY")

            # 阿里云百炼的 base_url
            client = OpenAI(
                api_key=api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
            )

            response = client.chat.completions.create(
                model="qwen-plus",  # 或其他可用模型
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=4000
            )

            return response.choices[0].message.content

        except ImportError:
            print("[!] 请安装 openai 包: pip install openai")
            return None
        except Exception as e:
            print(f"[!] 阿里云百炼 API 调用失败: {str(e)[:100]}")
            return None

    async def run_llm_analysis(self):
        """完整的 LLM 分析流程"""
        async with async_playwright() as p:
            await self.setup(p)

            # 访问首页
            await self.page.goto(self.start_url)
            await self.page.wait_for_load_state("networkidle")

            # 处理登录
            if await self.is_login_required():
                await self.wait_for_user_login()
                await self.page.goto(self.start_url)
                await self.page.wait_for_load_state("networkidle")

            # 1. 多方向滚动探索页面
            print("\n=== Phase 1: 页面探索 ===")
            await self.scroll_explore_all_directions()

            # 2. 捕获页面信息
            page_data = await self.capture_page_for_llm()

            # 3. LLM 分析
            print("\n=== Phase 2: LLM 智能分析 ===")
            llm_result = await self.analyze_with_llm(page_data)

            if llm_result:
                # 保存分析结果
                self.results["llm_analysis"] = llm_result

            # 4. 根据 LLM 结果生成操作序列
            print("\n=== Phase 3: 生成操作序列 ===")
            operations = llm_result.get("operations", [])
            business_buttons = llm_result.get("business_buttons", [])

            print(f"[+] 发现 {len(business_buttons)} 个业务按钮")
            print(f"[+] 发现 {len(operations)} 个可执行操作")

            # 5. 执行关键操作
            for btn_info in business_buttons[:10]:  # 限制操作数量
                btn_text = btn_info.get("text", "")
                action_type = btn_info.get("action", "other")
                print(f"[*] 准备执行: {btn_text} ({action_type})")

                # 尝试点击按钮
                await self._try_click_button(btn_text)
                await asyncio.sleep(1)

                # 检测结果
                post_url = self.page.url
                post_modals = await self.detect_modals_and_drawers()

                if post_modals:
                    await self.capture_current_state(f"modal_{btn_text[:10]}")
                    await self.page.keyboard.press("Escape")

                # 记录交互
                self.results["interactions"].append({
                    "button": btn_text,
                    "action_type": action_type,
                    "description": btn_info.get("description", ""),
                    "result": "success" if post_modals else "clicked"
                })

        return llm_result

    async def _try_click_button(self, text):
        """尝试点击指定文本的按钮"""
        try:
            # 方法1: 使用 get_by_text
            element = await self.page.get_by_text(text, exact=False).first
            if element and await element.is_visible():
                await element.click()
                return True
        except:
            pass

        # 方法2: 遍历所有按钮
        try:
            buttons = await self.page.query_selector_all("button, a, [role='button']")
            for btn in buttons[:20]:
                try:
                    btn_text = (await btn.inner_text()).strip()
                    if text in btn_text or btn_text in text:
                        if await btn.is_visible():
                            await btn.click()
                            return True
                except:
                    continue
        except:
            pass

        return False

    async def run(self):
        """主入口 - 混合方案流程"""
        async with async_playwright() as p:
            await self.setup(p)

            # 访问首页
            await self.page.goto(self.start_url)
            await self.page.wait_for_load_state("networkidle")

            # 处理登录 - 等待用户输入认证信息并点击确认按钮后才认为登录完成
            if await self.is_login_required():
                await self.wait_for_user_login()
                await self.page.goto(self.start_url)
                await self.page.wait_for_load_state("networkidle")

            # 开始抓取
            print("[*] 开始 UI/UX 逆向抓取...")

            # Phase 1: 多方向滚动探索（新增）
            print("\n=== Phase 1: 页面探索 ===")
            await self.scroll_to_load_all()  # 原有垂直滚动
            await self.scroll_explore_all_directions()  # 新增多方向滚动

            # Phase 2: 导航结构分析（新增）
            print("\n=== Phase 2: 导航结构分析 ===")
            await self.analyze_navigation_structure()

            # Phase 3: 表单和操作分析（新增）
            print("\n=== Phase 3: 表单和操作分析 ===")
            await self.analyze_forms_and_operations()

            # Phase 4: 智能交互探索
            print("\n=== Phase 4: 智能交互探索 ===")
            await self.auto_explore()

            # 生成 Markdown
            markdown = self.generate_markdown()

            # 保存结果
            results_copy = {
                "pages": self.results["pages"],
                "interactions": self.results["interactions"]
            }

            # 添加导航和表单分析结果
            if "navigation" in self.results:
                results_copy["navigation"] = self.results["navigation"]
            if "forms_analysis" in self.results:
                results_copy["forms_analysis"] = self.results["forms_analysis"]

            with open("ui_analysis_report.json", "w", encoding="utf-8") as f:
                json.dump(results_copy, f, ensure_ascii=False, indent=2)

            with open("ui_analysis_report.md", "w", encoding="utf-8") as f:
                f.write(markdown)

            print("\n[OK] 完成！")
            print(f"  - JSON: ui_analysis_report.json")
            print(f"  - Markdown: ui_analysis_report.md")
            print(f"  - 截图: screenshot_*.png")

            # 保持浏览器打开以便查看
            # await self.browser.close()


if __name__ == "__main__":
    import sys

    # 解析命令行参数
    # 用法: python ui_agent.py <URL> [max_depth] [--mode=auto|llm]
    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    depth = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 10

    # 解析模式
    mode = "auto"
    for arg in sys.argv[3:]:
        if arg.startswith("--mode="):
            mode = arg.split("=")[1]

    print(f"[+] 目标页面: {url}")
    print(f"[+] 最大深度: {depth}")
    print(f"[+] 运行模式: {mode}")

    if mode == "llm":
        print("\n*** 使用 LLM 辅助分析模式 ***\n")
        # 检查 API Key
        import os
        if not os.environ.get("DASHSCOPE_API_KEY"):
            print("[!] 请设置 DASHSCOPE_API_KEY 环境变量")
            print("[!] 示例: set DASHSCOPE_API_KEY=sk-...")
            sys.exit(1)

        agent = AutoUXAgent(url, max_depth=depth)
        asyncio.run(agent.run_llm_analysis())

        # 保存结果
        results_copy = {
            "pages": agent.results["pages"],
            "interactions": agent.results["interactions"]
        }
        if "llm_analysis" in agent.results:
            results_copy["llm_analysis"] = agent.results["llm_analysis"]

        with open("ui_analysis_report.json", "w", encoding="utf-8") as f:
            json.dump(results_copy, f, ensure_ascii=False, indent=2)

        with open("ui_analysis_report.md", "w", encoding="utf-8") as f:
            f.write(agent.generate_markdown())

        print("\n[OK] 分析完成！")

    else:
        print("\n*** 使用自动化分析模式 ***\n")
        agent = AutoUXAgent(url, max_depth=depth)
        asyncio.run(agent.run())
