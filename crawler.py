"""
银豹云后台数据抓取模块
使用 Playwright 模拟浏览器登录，自动抓取销售数据
"""

import json
import os
import random
import re
import time
import logging
from typing import Optional

from playwright.sync_api import sync_playwright, Page

logger = logging.getLogger(__name__)


class YinbaoCrawler:
    """POS 后台数据抓取器"""

    LOGIN_URL = "https://beta.pospal.cn/account/signin"

    def __init__(self, config: dict):
        self.config = config
        self.account = os.getenv("POS_ACCOUNT", "")
        self.password = os.getenv("POS_PASSWORD", "")
        self.headless = config["run"].get("headless", True)
        self.timeout = config["run"].get("timeout", 30000)
        self.cookie_path = "pospal_cookies.json"
        # 真人模拟延迟范围
        self.min_delay = config["run"].get("min_delay", 1.0)
        self.max_delay = config["run"].get("max_delay", 3.0)

    def _pause(self, label: str = "") -> None:
        """模拟真人间歇——每次操作后随机停顿

        人类不会秒点下一个按钮，会有 1-3 秒的自然停顿。
        这个停顿让操作节奏像真人在浏览器里手动操作。
        """
        delay = random.uniform(self.min_delay, self.max_delay)
        if label:
            logger.debug(f"  [停顿 {delay:.1f}s] {label}")
        time.sleep(delay)

    def run(self) -> Optional[dict]:
        """执行完整的数据抓取流程"""
        logger.info("=" * 50)
        logger.info("开始启动浏览器...")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            page = context.new_page()
            page.set_default_timeout(self.timeout)

            try:
                # ========== 第一步：登录 ==========
                if not self._login(page):
                    logger.error("登录失败，终止抓取")
                    return None

                # ========== 关闭公告弹窗 ==========
                self._pause("等弹窗加载")
                self._close_announcement(page)
                self._pause("关闭弹窗后")

                # ========== 第二步：首页抓取营业实收 ==========
                logger.info("\n--- 正在抓取首页数据 ---")
                data = {}

                # 提取营业实收
                labels = ["营业实收"]
                for label in labels:
                    val = self._extract_value_after_label(page, label)
                    if val:
                        data[label] = val
                        logger.info(f"  {label}: {val}")

                # ========== 第三步：向下滚动抓取商品消费单数排名 ==========
                logger.info("\n--- 正在抓取商品消费单数排名 ---")

                # 先把鼠标移到视口中央，再用 evaluate 滚动（mouse.wheel 单独用常常不生效）
                self._pause("看数据")
                page.mouse.move(960, 540)
                time.sleep(0.3)

                ranking_el = page.locator('text=商品消费单数排名').first
                if ranking_el.count() == 0:
                    logger.info("  首次未找到，开始向下滚动加载...")
                    for i in range(10):
                        page.evaluate("window.scrollBy(0, 1000)")
                        time.sleep(0.6)
                        if ranking_el.count() > 0:
                            logger.info(f"  第 {i+1} 次滚动后找到元素")
                            break

                if ranking_el.count() > 0:
                    try:
                        ranking_el.scroll_into_view_if_needed(timeout=5000)
                        time.sleep(2)
                        # 优先用 Playwright 选择器直接从页面提取结构化数据
                        products = self._parse_product_ranking_from_page(page)
                        if products:
                            data["商品消费单数排名"] = products
                            logger.info(f"  提取到 {len(products)} 个商品")
                            for i, p in enumerate(products[:5], 1):
                                logger.info(f"    {i}. {p['name']}: {p['count']}单")
                        else:
                            # 降级：保存原始文本
                            logger.warning("  未能解析出商品数据，保存原始文本")
                            parent = ranking_el.locator(
                                "xpath=ancestor::div[contains(@class,'card') or contains(@class,'panel') "
                                "or contains(@class,'box') or contains(@class,'rank')][1]"
                            ).first
                            text = parent.inner_text() if parent.count() > 0 else ""
                            if not text:
                                text = ranking_el.locator("xpath=../..").inner_text()
                            if text:
                                data["_商品消费单数排名_原始"] = text
                    except Exception as e:
                        logger.warning(f"  滚动或提取失败: {e}")
                else:
                    logger.warning("  滚动 10 次仍未找到'商品消费单数排名'区域")

                # ========== 第四步：向上滚动回到顶部 ==========
                logger.info("\n--- 向上滚动回到顶部 ---")
                self._pause("看完排名，回到顶部")
                page.evaluate("window.scrollTo(0, 0)")
                self._pause("等页面回到顶部")

                # ========== 第五步：进入营业概况明细 ==========
                # "更多"在新标签页打开，URL 固定为 /Report/BusinessSummaryV2
                # 直接导航即可——Cookie 已登录，不需要重新认证
                logger.info("\n--- 正在进入营业概况明细 ---")
                detail_url = "https://beta30.pospal.cn/Report/BusinessSummaryV2"
                logger.info(f"  导航: {detail_url}")
                page.goto(detail_url, wait_until="networkidle")
                time.sleep(3)
                logger.info(f"  当前页面: {page.url}")

                # ========== 第六步：在营业概况明细页抓取数据 ==========
                # 提取右上角时间跨度
                time_range = self._extract_time_range(page)
                if time_range:
                    data["查询时间跨度"] = time_range
                    logger.info(f"  查询时间跨度: {time_range}")

                # 保存页面 HTML（调试用）
                try:
                    html = page.content()
                    with open("business_overview.html", "w", encoding="utf-8") as f:
                        f.write(html)
                except Exception:
                    pass

                # 从营业概况表格中精确提取：储值卡充值 / 次卡销售 / 会员付费升级 的"现金支付"列
                # HTML 结构：
                #   <tr data-row-title="储值卡充值">
                #     <td class="tdAlignRight"><span data-show-name="现金支付">1100.00</span></td>
                target_rows = [
                    # (定位方式, 数据key, 说明)
                    ('tr[data-row-key="memberCard"]', "储值卡充值"),
                    ('tr[data-row-key="passProduct"]', "次卡销售"),
                    ('tr:has(a:has-text("会员付费升级"))', "会员付费升级"),  # 这行没有 data-row-key
                ]
                for selector, data_key in target_rows:
                    try:
                        row = page.locator(selector).first
                        if row.count() > 0:
                            cash_span = row.locator('span[data-show-name="现金支付"]').first
                            if cash_span.count() > 0:
                                val = cash_span.inner_text().strip()
                                data[data_key] = val
                                logger.info(f"  {data_key}: {val}")
                            else:
                                logger.warning(f"  未找到{data_key}的现金支付列")
                        else:
                            logger.warning(f"  未找到{data_key}行")
                    except Exception as e:
                        logger.warning(f"  提取{data_key}失败: {e}")

                logger.info("\n" + "=" * 50)
                logger.info("全部数据抓取完成！")
                logger.info("=" * 50)
                return data

            except Exception as e:
                logger.error(f"抓取过程出错: {e}")
                page.screenshot(path="error_screenshot.png")
                return None
            finally:
                browser.close()

    def _login(self, page: Page) -> bool:
        """登录银豹云后台"""
        logger.info(f"正在打开登录页: {self.LOGIN_URL}")

        # 尝试加载之前保存的 cookies
        try:
            with open(self.cookie_path, "r") as f:
                cookies = json.load(f)
            page.goto("https://user.pospal.cn", wait_until="domcontentloaded")
            page.context.add_cookies(cookies)
            page.goto("https://user.pospal.cn", wait_until="networkidle")
            time.sleep(2)
            if "signin" not in page.url.lower():
                logger.info("Cookie 登录成功，跳过账号密码输入")
                return True
            else:
                logger.info("Cookie 已过期，使用账号密码登录")
        except (FileNotFoundError, json.JSONDecodeError):
            logger.info("未找到 Cookie，尝试账号密码登录")

        # 正常填写账号密码登录
        page.goto(self.LOGIN_URL, wait_until="networkidle")
        time.sleep(2)

        # 填写账号
        logger.info("填写账号...")
        try:
            account_input = page.get_by_placeholder("请输入账号")
            if account_input.count() > 0:
                account_input.fill(self.account)
            else:
                page.locator('input[name="account"], input[type="text"]').first.fill(self.account)
        except Exception:
            page.locator('input[type="text"]').first.fill(self.account)

        # 填写密码
        logger.info("填写密码...")
        try:
            pwd_input = page.get_by_placeholder("请输入密码")
            if pwd_input.count() > 0:
                pwd_input.fill(self.password)
            else:
                page.locator('input[name="password"], input[type="password"]').first.fill(self.password)
        except Exception:
            page.locator('input[type="password"]').first.fill(self.password)

        # 点击登录按钮
        logger.info("点击登录...")
        try:
            # 尝试多种选择器
            btn = page.get_by_role("button", name=re.compile(r"登录|登入|登錄"))
            if btn.count() > 0:
                btn.click()
            else:
                btn = page.locator('button[type="submit"]')
                if btn.count() > 0:
                    btn.click()
                else:
                    # 尝试通过文字匹配
                    btn = page.locator('button:has-text("登录"), button:has-text("登入"), button:has-text("Login")')
                    if btn.count() > 0:
                        btn.first.click()
                    else:
                        # 最后尝试按回车键
                        page.keyboard.press("Enter")
        except Exception:
            page.keyboard.press("Enter")

        # 等待跳转 - 检查是否离开登录页
        time.sleep(3)
        try:
            page.wait_for_url("**/Dashboard/**", timeout=20000)
            logger.info("登录成功！")
            try:
                cookies = page.context.cookies()
                with open(self.cookie_path, "w") as f:
                    json.dump(cookies, f)
            except Exception:
                pass
            return True
        except Exception:
            if "signin" in page.url.lower():
                logger.error("登录失败！还在登录页，请检查账号密码")
                return False
            logger.info(f"已跳转到: {page.url}，继续执行...")
            return True

    def _close_announcement(self, page: Page):
        """关闭登录后可能出现的公告弹窗"""
        time.sleep(2)  # 等待弹窗加载
        try:
            # 尝试多种关闭按钮选择器
            close_selectors = [
                'button:has-text("关闭")',
                'button:has-text("确定")',
                'button:has-text("知道了")',
                'button:has-text("我知道了")',
                'button:has-text("取消")',
                '.modal-close',
                '.close-btn',
                '[class*="close"]',
                'button[aria-label="Close"]',
            ]
            for selector in close_selectors:
                btn = page.locator(selector).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click()
                    logger.info(f"已关闭公告弹窗: {selector}")
                    time.sleep(1)
                    return
        except Exception as e:
            logger.debug(f"未检测到公告弹窗或关闭失败: {e}")

    def _click_left_nav(self, page: Page, *menu_items: str):
        """按顺序点击左侧导航菜单项"""
        for item_text in menu_items:
            try:
                locator = page.locator(f"text={item_text}").first
                if locator.count() == 0:
                    locator = page.locator(f"span:has-text('{item_text}')").first
                if locator.count() == 0:
                    locator = page.locator(f'[class*="menu"]:has-text("{item_text}")').first
                if locator.count() > 0:
                    locator.click()
                    time.sleep(1.5)
                    logger.info(f"  点击导航: {item_text}")
            except Exception as e:
                logger.warning(f"  点击 '{item_text}' 出错: {e}")

    def _extract_value_after_label(self, page: Page, label: str) -> str:
        """提取某个文本标签旁边/下面的数值"""
        try:
            el = page.locator(f"text={label}").first
            if el.count() > 0:
                parent = el.locator("..")
                full_text = parent.inner_text()
                if full_text:
                    nums = re.findall(r"[-]?\d+\.?\d*", full_text.replace(",", ""))
                    if nums:
                        return nums[0]
        except Exception:
            pass
        return ""

    def _extract_table_text(self, page: Page) -> str:
        """提取页面表格文本；找不到标准表格时退化到抓主区域文本"""
        selectors = [
            'table',
            '[class*="table"]',
            '[class*="grid"]',
            '[class*="report"]',
            '[class*="detail"]',
            '[role="grid"]',
            '[role="table"]',
        ]
        best = ""
        for sel in selectors:
            el = page.locator(sel).first
            if el.count() > 0:
                try:
                    text = el.inner_text()
                    if len(text) > 50:
                        # 取内容最长的那个，避免拿到小卡片
                        if len(text) > len(best):
                            best = text
                except Exception:
                    continue
        if best:
            return best
        # 兜底：抓整个页面文本，让 _extract_value_near_label 兜底
        try:
            full = page.inner_text("body")
            if len(full) > 100:
                return full
        except Exception:
            pass
        return ""

    def _extract_value_near_label(self, text: str, label: str) -> str:
        """从文本中提取 label 后面的金额，支持 ¥1,234.56 / 1234.56 / -1,234 等"""
        # 先切掉 label 之前的无关内容，避免匹配到别处的同名子串
        idx = text.find(label)
        if idx < 0:
            return ""
        tail = text[idx + len(label): idx + len(label) + 80]
        # 匹配可选符号、可选¥、可选千分位逗号、小数
        pat = re.compile(r"[-—]?\s*[¥￥]?\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)")
        m = pat.search(tail)
        if m:
            raw = m.group(1)
            return raw.replace(",", "")  # 统一去逗号，返回纯数字字符串
        return ""

    def _parse_product_ranking_from_page(self, page: Page) -> list:
        """从页面提取商品消费单数排名

        限定在"商品消费单数排名"这个卡片内、且"销量"标签页激活时。
        页面可能有多个 commodity__item（销售额排名、消费单数排名等），
        必须用标题文字精确锁定，否则会抓到别的排名区。
        """
        products = []
        try:
            # Step 1: 找到"商品消费单数排名"这个卡片
            ranking_card = page.locator('.commodity__item:has-text("商品消费单数排名")').first
            if ranking_card.count() == 0:
                logger.warning("  未找到'商品消费单数排名'卡片")
                return products

            # Step 2: 确认"销量"标签是激活状态（不是"金额"标签）
            active_tab = ranking_card.locator('span.tab.active').first
            if active_tab.count() > 0:
                tab_text = active_tab.inner_text().strip()
                logger.info(f"  当前激活标签: {tab_text}")
            else:
                logger.warning("  未找到激活标签，可能默认就是销量")

            # Step 3: 在这个卡片内找所有商品条目
            bars = ranking_card.locator('.percentBar').all()
            logger.info(f"  找到 {len(bars)} 个商品条目")

            for bar in bars:
                try:
                    # 商品名 — .percentBar__top-left
                    name_el = bar.locator('.percentBar__top-left').first
                    if name_el.count() == 0:
                        continue
                    name = name_el.inner_text().strip()

                    # 跳过表头和其他非商品文本
                    if not name or '商品' in name:
                        continue

                    # 数量 — 第一个 .percentBar__tipItem 里是 "数量 84个"
                    qty_el = bar.locator('.percentBar__tipItem').first
                    if qty_el.count() == 0:
                        continue
                    qty_text = qty_el.inner_text()
                    match = re.search(r'(\d+)', qty_text)
                    qty = match.group(1) if match else "0"

                    products.append({'name': name, 'count': qty})
                except Exception:
                    continue

            logger.info(f"  成功提取 {len(products)} 个商品")
        except Exception as e:
            logger.warning(f"  从页面提取商品排名失败: {e}")

        return products

    def _parse_product_ranking(self, text: str) -> list:
        """解析商品消费单数排名文本 — 旧版（正则方式，保留兼容）"""
        products = []
        try:
            # 尝试旧格式：商品名 数量单（如 "奶茶 120单"）
            pattern = re.compile(r'([^\d\n]+?)\s+(\d+)\s*单')
            matches = pattern.findall(text)

            for name, count in matches:
                name = name.strip()
                if name and '商品消费单数排名' not in name and len(name) > 0:
                    products.append({
                        'name': name,
                        'count': count
                    })
        except Exception as e:
            logger.warning(f"解析商品排名失败: {e}")

        return products

    def _extract_time_range(self, page: Page) -> str:
        """提取页面右上角的时间跨度"""
        try:
            time_el = page.locator('[class*="time"], [class*="date"], [class*="range"]').first
            if time_el.count() > 0:
                text = time_el.inner_text().strip()
                if re.search(r"\d{4}.\d{2}.\d{2}", text):
                    return text

            page_text = page.inner_text("body")
            match = re.search(r"(\d{4}.\d{2}.\d{2}\s+\d{2}:\d{2}\s*[-–—]\s*\d{4}.\d{2}.\d{2}\s+\d{2}:\d{2})", page_text)
            if match:
                return match.group(1).strip()
        except Exception as e:
            logger.warning(f"  提取时间跨度失败: {e}")
        return ""

    def _scrape_overview(self, page: Page) -> dict:
        """抓取概览页核心数据，点击更多进入明细页提取关键收入和时间跨度"""
        data = {}
        page.goto("https://user.pospal.cn/", wait_until="networkidle")
        time.sleep(3)

        # 保存页面 HTML（调试用）
        try:
            html = page.content()
            with open("overview_page.html", "w", encoding="utf-8") as f:
                f.write(html)
        except Exception:
            pass

        # 提取营业实收
        labels = ["营业实收"]
        for label in labels:
            val = self._extract_value_after_label(page, label)
            if val:
                data[label] = val

        logger.info(f"  营业实收: {data.get('营业实收', 'N/A')}")

        # 点击"更多"进入营业概况明细页
        logger.info("  尝试点击'更多'进入营业概况明细...")
        clicked_more = False
        try:
            more_btn = page.get_by_text("更多").first
            if more_btn.count() > 0:
                more_btn.click()
                time.sleep(3)
                clicked_more = True
                logger.info("  已点击'更多'，进入营业概况明细页")
            else:
                logger.warning("  未找到'更多'按钮")
        except Exception as e:
            logger.warning(f"  点击'更多'失败: {e}")

        if not clicked_more:
            logger.info("  尝试通过左侧导航进入营业概况...")
            self._click_left_nav(page, "营业概况")
            time.sleep(3)
            if "营业概况" not in page.content():
                self._click_left_nav(page, "销售")
                time.sleep(1)
                self._click_left_nav(page, "营业概况")
                time.sleep(3)

        # 提取右上角时间跨度
        time_range = self._extract_time_range(page)
        if time_range:
            data["查询时间跨度"] = time_range
            logger.info(f"  查询时间跨度: {time_range}")

        # 提取4项关键收入数据
        try:
            html = page.content()
            with open("business_overview.html", "w", encoding="utf-8") as f:
                f.write(html)
        except Exception:
            pass

        table_text = self._extract_table_text(page)
        if table_text:
            data["_营业概况表_原始"] = table_text
            logger.info(f"  表格内容长度: {len(table_text)} 字符")

            target_items = [
                ("储值卡充值", "储值卡充值"),
                ("次卡销售", "次卡销售"),
                ("礼品包销售", "礼品包销售"),
                ("会员付费升级", "会员付费升级"),
            ]
            for label, key in target_items:
                val = self._extract_value_near_label(table_text, label)
                if val:
                    data[key] = val
                    logger.info(f"  {key}: {val}")

        return data

    def _scrape_product_sales(self, page: Page) -> dict:
        """在首页往下滚动，抓取商品消费单数排名"""
        data = {}

        page.goto("https://user.pospal.cn/", wait_until="networkidle")
        time.sleep(3)

        logger.info("  向下滚动查看商品消费单数排名...")
        for _ in range(5):
            page.mouse.wheel(0, 800)
            time.sleep(1)

        try:
            html = page.content()
            with open("product_sales.html", "w", encoding="utf-8") as f:
                f.write(html)
        except Exception:
            pass

        ranking_el = page.locator('text=商品消费单数排名').first
        if ranking_el.count() > 0:
            parent = ranking_el.locator("xpath=ancestor::div[contains(@class,'card') or contains(@class,'panel') or contains(@class,'box') or ..]").first
            text = parent.inner_text() if parent.count() > 0 else ""
            if not text:
                text = ranking_el.locator("xpath=../..").inner_text()
            if text:
                data["_商品消费单数排名_原始"] = text
                logger.info(f"  商品消费单数排名内容长度: {len(text)} 字符")
        else:
            logger.warning("  未找到'商品消费单数排名'区域")
            table_text = self._extract_table_text(page)
            if table_text:
                data["_商品销售_原始"] = table_text
                logger.info(f"  商品销售表格内容长度: {len(table_text)} 字符")

        return data
