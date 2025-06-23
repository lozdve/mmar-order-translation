import os
import time
os.environ['TZ'] = 'Asia/Shanghai'
time.tzset()  # 这一行在 Unix/Linux 系统上很重要
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import openai
from datetime import datetime, timedelta

import json



# 页面配置
st.set_page_config(
    page_title="📋 订单翻译工具",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed"
)

class OrderTranslator:
    def __init__(self):
        self.gc = None
        self.spreadsheet = None
        self.usage_stats = {"orders_processed": 0, "tokens_used": 0}
        
    def initialize_with_secrets(self) -> bool:
        """使用Streamlit Secrets初始化所有连接"""
        try:
            # 检查OpenAI配置
            if "openai" not in st.secrets:
                st.error("⚠️ 管理员需要配置OpenAI API密钥")
                with st.expander("📖 配置说明"):
                    st.code("""
# 在Streamlit Cloud Secrets中添加：
[openai]
api_key = "sk-your-openai-api-key"
                    """)
                return False
            
            # 检查Google凭据
            if "google_credentials" not in st.secrets:
                st.error("⚠️ 管理员需要配置Google凭据")
                with st.expander("📖 配置说明"):
                    st.code("""
# 在Streamlit Cloud Secrets中添加：
[google_credentials]
type = "service_account"
project_id = "your-project-id"
# ... 其他Google凭据字段
                    """)
                return False
            
            # 设置OpenAI
            openai.api_key = st.secrets["openai"]["api_key"]
            
            # 设置Google Sheets
            credentials_dict = dict(st.secrets["google_credentials"])
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            credentials = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
            self.gc = gspread.authorize(credentials)
            
            # 连接表格
            sheet_url = st.secrets.get("app_settings", {}).get("sheet_url", 
                "https://docs.google.com/spreadsheets/d/1g_xoXrBy8MnG_76nrRAT9eNaMytE5YrCYBUK3q5AE04")
            spreadsheet_id = sheet_url.split('/spreadsheets/d/')[1].split('/')[0]
            self.spreadsheet = self.gc.open_by_key(spreadsheet_id)
            
            return True
            
        except Exception as e:
            st.error(f"❌ 初始化失败: {e}")
            
            # 提供详细的错误帮助
            with st.expander("🔧 故障排除"):
                st.markdown("""
                **可能的问题：**
                1. Streamlit Secrets配置不正确
                2. Google服务账号权限不足
                3. OpenAI API密钥无效
                4. Google Sheets未分享给服务账号
                
                **解决步骤：**
                1. 检查Streamlit Cloud → Settings → Secrets配置
                2. 确认Google Sheets已分享给服务账号邮箱
                3. 验证OpenAI API密钥有效且有余额
                """)
            return False
    
    def translate_text(self, text: str) -> str:
        """翻译文本"""
        if not text or text.strip() == '':
            return ''
        
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{
                    "role": "user", 
                    "content": f"请将以下中文内容翻译成英文，保持专业术语的准确性，只返回翻译结果：\n\n{text}"
                }],
                max_tokens=2000,
                temperature=0.3
            )
            
            # 统计使用量
            if "usage" in response:
                self.usage_stats["tokens_used"] += response["usage"]["total_tokens"]
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            st.warning(f"翻译失败: {e}")
            return f"[Translation Failed] {text}"
    
    def format_uw_instructions(self, call_content: str, review_advice: str, need_call: bool) -> str:
        """格式化UW指令"""
        formatted_text = "═══ THE APPROVAL RESULT SHALL BE PROVIDED AFTER RISK INVESTIGATION.@UW ═══\n"
        
        if need_call:
            formatted_text += "═══ NEED TO CALL AND CONFIRM THE FOLLOWING QUESTIONS： ═══\n\n"
            formatted_text += (call_content.strip() if call_content else "[No call content]") + "\n\n"
        else:
            formatted_text += (call_content.strip() if call_content else "[No content]") + "\n\n"
        
        formatted_text += "═══ REVIEW ADVICE： ═══\n"
        formatted_text += (review_advice.strip() if review_advice else "[No advice]")
        
        return formatted_text
    
    def get_usage_info(self):
        """获取使用统计"""
        settings = st.secrets.get("app_settings", {})
        monthly_budget = settings.get("monthly_budget", 100)
        max_daily_orders = settings.get("max_daily_orders", 500)
        
        # 估算成本
        estimated_cost = (self.usage_stats["tokens_used"] / 1000) * 0.002
        
        return {
            "orders_processed": self.usage_stats["orders_processed"],
            "tokens_used": self.usage_stats["tokens_used"],
            "estimated_cost": estimated_cost,
            "monthly_budget": monthly_budget,
            "max_daily_orders": max_daily_orders
        }
    
    def process_orders(self, cutoff_date: datetime, progress_container=None, status_container=None):
        """处理订单"""
        try:
            # 获取配置
            settings = st.secrets.get("app_settings", {})
            source_sheet_name = settings.get("source_sheet", "支援审核订单详情")
            target_sheet_name = settings.get("target_sheet", "电核订单英文翻译")
            
            # 显示初始化状态
            if status_container:
                status_container.info("📋 正在读取表格数据...")
            
            # 获取数据
            worksheet = self.spreadsheet.worksheet(source_sheet_name)
            data = worksheet.get_all_values()
            
            if not data:
                return {"success": False, "message": "表格没有数据"}
            
            headers = data[0]
            
            # 查找列索引
            if status_container:
                status_container.info("🔍 正在识别表格列...")
                
            column_map = {
                'date': ['审核日期', '日期'],
                'order_id': ['订单编号', '订单号'],
                'need_call': ['是否需要电核', '需要电核'],
                'review_details': ['审核详情', '详情'],
                'call_content': ['需要电核的内容', '电核内容'],
                'review_advice': ['信审审核意见', '信审意见']
            }
            
            indices = {}
            for key, possible_names in column_map.items():
                indices[key] = -1
                for name in possible_names:
                    try:
                        indices[key] = headers.index(name)
                        break
                    except ValueError:
                        continue
                
                if indices[key] == -1:
                    return {"success": False, "message": f"找不到列: {possible_names[0]}"}
            
            # 筛选数据
            if status_container:
                status_container.info("📅 正在筛选符合条件的订单...")
                
            filtered_orders = []
            total_rows = len(data) - 1  # 排除表头
            
            for i, row in enumerate(data[1:], 1):
                try:
                    if len(row) <= max(indices.values()):
                        continue
                    
                    date_str = row[indices['date']]
                    review_date = None
                    
                    # 尝试多种日期格式
                    for date_format in ['%Y/%m/%d', '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y']:
                        try:
                            review_date = datetime.strptime(date_str, date_format)
                            break
                        except ValueError:
                            continue
                    
                    if review_date and review_date >= cutoff_date:
                        filtered_orders.append(row)
                        
                except Exception:
                    continue
            
            if not filtered_orders:
                return {"success": False, "message": f"没有找到 {cutoff_date.strftime('%Y-%m-%d')} 及以后的订单"}
            
            # 显示筛选结果
            if status_container:
                status_container.success(f"✅ 找到 {len(filtered_orders)} 个符合条件的订单（共扫描 {total_rows} 行数据）")
            
            # 检查限制
            usage_info = self.get_usage_info()
            if len(filtered_orders) > usage_info["max_daily_orders"]:
                return {
                    "success": False,
                    "message": f"订单数量({len(filtered_orders)})超过每日限制({usage_info['max_daily_orders']})"
                }
            
            # 创建目标工作表
            if status_container:
                status_container.info("📝 正在准备输出表格...")
                
            try:
                target_ws = self.spreadsheet.worksheet(target_sheet_name)
                target_ws.clear()
            except gspread.WorksheetNotFound:
                target_ws = self.spreadsheet.add_worksheet(
                    title=target_sheet_name, 
                    rows=len(filtered_orders) + 10, 
                    cols=5
                )
            
            # 设置表头
            headers_row = ['Review Date', 'Order ID', 'Review Details', 'UW Instructions', 'Processing Date']
            target_ws.update('A1:E1', [headers_row])
            
            if status_container:
                status_container.info("🚀 开始翻译处理...")
            
            # 处理订单
            processed_data = []
            today = datetime.now().strftime('%Y-%m-%d')
            total_orders = len(filtered_orders)
            
            for i, row in enumerate(filtered_orders):
                current_order = i + 1
                
                # 更新进度
                if progress_container:
                    progress = current_order / total_orders
                    progress_container.progress(progress)
                
                if status_container:
                    order_id = row[indices['order_id']] if len(row) > indices['order_id'] else f"订单{current_order}"
                    status_container.info(f"🔄 正在处理第 {current_order}/{total_orders} 个订单: {order_id}")
                
                try:
                    review_date = row[indices['date']]
                    order_id = row[indices['order_id']]
                    review_details = row[indices['review_details']]
                    call_content = row[indices['call_content']]
                    review_advice = row[indices['review_advice']]
                    need_call = row[indices['need_call']] in ['是', 'YES', 'yes']
                    
                    # 翻译处理（添加子步骤提示）
                    if status_container:
                        status_container.info(f"🌐 正在翻译订单 {order_id} - 审核详情...")
                    translated_details = self.translate_text(review_details)
                    time.sleep(0.3)
                    
                    if status_container:
                        status_container.info(f"🌐 正在翻译订单 {order_id} - 电核内容...")
                    translated_call = self.translate_text(call_content)
                    time.sleep(0.3)
                    
                    if status_container:
                        status_container.info(f"🌐 正在翻译订单 {order_id} - 信审意见...")
                    translated_advice = self.translate_text(review_advice)
                    time.sleep(0.3)
                    
                    # 格式化
                    uw_instructions = self.format_uw_instructions(
                        translated_call, translated_advice, need_call
                    )
                    
                    processed_data.append([
                        review_date, order_id, translated_details, uw_instructions, today
                    ])
                    
                    self.usage_stats["orders_processed"] += 1
                    
                    if status_container:
                        status_container.success(f"✅ 订单 {order_id} 处理完成 ({current_order}/{total_orders})")
                    
                except Exception as e:
                    if status_container:
                        status_container.warning(f"⚠️ 订单 {current_order} 处理失败: {e}")
                    continue
            
            # 写入数据
            if status_container:
                status_container.info("💾 正在保存翻译结果...")
                
            if processed_data:
                # 分批写入
                batch_size = 20
                total_batches = (len(processed_data) + batch_size - 1) // batch_size
                
                for batch_num in range(total_batches):
                    start_idx = batch_num * batch_size
                    end_idx = min((batch_num + 1) * batch_size, len(processed_data))
                    batch = processed_data[start_idx:end_idx]
                    
                    start_row = start_idx + 2
                    end_row = start_row + len(batch) - 1
                    
                    if status_container:
                        status_container.info(f"💾 保存批次 {batch_num + 1}/{total_batches} (行 {start_row}-{end_row})")
                    
                    target_ws.update(f'A{start_row}:E{end_row}', batch)
                    time.sleep(1)
                
                # 格式化
                if status_container:
                    status_container.info("🎨 正在格式化表格...")
                target_ws.format('A1:E1', {'textFormat': {'bold': True}})
                target_ws.format('D:D', {'wrapStrategy': 'WRAP'})
            
            if status_container:
                status_container.success(f"🎉 全部完成！成功处理 {len(processed_data)} 个订单")
            
            return {
                "success": True,
                "message": f"成功处理 {len(processed_data)} 个订单",
                "count": len(processed_data),
                "total_found": len(filtered_orders),
                "usage": self.get_usage_info()
            }
            
        except Exception as e:
            if status_container:
                status_container.error(f"❌ 处理过程中发生错误: {str(e)}")
            return {"success": False, "message": f"处理失败: {str(e)}"}

def check_access_control():
    """检查访问控制"""
    access_config = st.secrets.get("access_control", {})
    
    if not access_config.get("enabled", False):
        return True  # 如果未启用访问控制，直接通过
    
    # 检查session state中是否已认证
    if st.session_state.get("authenticated", False):
        return True
    
    # 显示登录界面
    st.title("🔐 团队访问验证")
    st.markdown("### 请输入团队访问密码")
    
    with st.form("access_form"):
        password = st.text_input(
            "访问密码", 
            type="password",
            placeholder="请输入团队密码"
        )
        
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            submit_button = st.form_submit_button(
                "🚀 进入系统", 
                type="primary",
                use_container_width=True
            )
        
        if submit_button:
            team_password = access_config.get("team_password", "")
            
            if password == team_password:
                st.session_state.authenticated = True
                st.success("✅ 验证成功！正在进入系统...")
                time.sleep(1)
                st.rerun()
            else:
                st.error("❌ 密码错误，请重试")
                time.sleep(2)
                st.rerun()
    
    # 显示提示信息
    st.markdown("---")
    st.info("""
    **🔒 访问说明：**
    - 本工具仅供团队内部使用
    - 请联系管理员获取访问密码
    - 密码验证通过后即可使用所有功能
    """)
    
    return False

def main():
    """主函数"""
    
    # 首先检查访问控制
    if not check_access_control():
        st.stop()
    
    # 显示登出选项（在侧边栏）
    access_config = st.secrets.get("access_control", {})
    if access_config.get("enabled", False):
        with st.sidebar:
            st.markdown("---")
            if st.button("🚪 退出系统"):
                st.session_state.authenticated = False
                st.rerun()
            
            # 显示当前用户状态
            st.success("🔓 已通过验证")
    
    # 页面标题
    st.title("📋 订单翻译工具")
    st.markdown("### ⚡ 零配置版本")
    
    # 初始化
    if 'translator' not in st.session_state:
        st.session_state.translator = OrderTranslator()
        st.session_state.initialized = False
    
    translator = st.session_state.translator
    
    # 检查初始化状态
    if not st.session_state.initialized:
        with st.spinner("🔄 正在初始化系统..."):
            st.session_state.initialized = translator.initialize_with_secrets()
    
    if not st.session_state.initialized:
        st.stop()
    
    # 成功初始化
    st.success("✅ 系统已就绪")
    st.markdown(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    # 主界面
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("📅 选择处理日期")
        
        # 日期选项
        date_options = {
            "📅 今天的订单": datetime.now().date(),
            "📅 昨天的订单": datetime.now().date() - timedelta(days=1),
            "📅 最近3天": datetime.now().date() - timedelta(days=2),
            "📅 最近一周": datetime.now().date() - timedelta(days=6),
            "📅 从6月20日开始": datetime(2025, 6, 20).date(),
            "📅 本月全部": datetime(datetime.now().year, datetime.now().month, 1).date()
        }
        
        selected_option = st.selectbox(
            "选择日期范围",
            list(date_options.keys()),
            index=0
        )
        
        cutoff_date = date_options[selected_option]
        st.info(f"📊 将处理 **{cutoff_date}** 及以后的所有订单")
    
    with col2:
        st.subheader("📊 使用统计")
        usage_info = translator.get_usage_info()
        
        st.metric("已处理订单", usage_info['orders_processed'])
        st.metric("Token消耗", f"{usage_info['tokens_used']:,}")
        st.metric("预估成本", f"${usage_info['estimated_cost']:.3f}")
        
        # 系统状态
        if usage_info['estimated_cost'] < usage_info['monthly_budget'] * 0.8:
            st.success("💚 系统正常")
        else:
            st.warning("🟡 接近预算")
    
    # 处理按钮
    st.markdown("---")
    
    # 使用标准按钮避免兼容性问题
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        process_button = st.button(
            "🚀 开始翻译处理", 
            type="primary",
            use_container_width=True
        )
    
    if process_button:
        st.markdown("### 📊 处理进度")
        
        # 创建进度显示容器
        progress_container = st.container()
        status_container = st.container()
        metrics_container = st.container()
        
        with progress_container:
            progress_bar = st.progress(0)
            
        with status_container:
            status_info = st.empty()
            
        with metrics_container:
            col1, col2, col3 = st.columns(3)
            with col1:
                current_orders_metric = st.empty()
            with col2:
                tokens_metric = st.empty()
            with col3:
                cost_metric = st.empty()
        
        # 开始处理
        cutoff_datetime = datetime.combine(cutoff_date, datetime.min.time())
        
        # 初始显示
        current_orders_metric.metric("处理进度", "0/0")
        tokens_metric.metric("Token消耗", "0")
        cost_metric.metric("预估成本", "$0.000")
        
        def update_metrics():
            """更新实时统计"""
            current_usage = translator.get_usage_info()
            tokens_metric.metric("Token消耗", f"{current_usage['tokens_used']:,}")
            cost_metric.metric("预估成本", f"${current_usage['estimated_cost']:.3f}")
        
        # 处理订单
        result = translator.process_orders(
            cutoff_datetime, 
            progress_bar, 
            status_info
        )
        
        # 显示结果
        if result["success"]:
            # 完成进度显示
            progress_bar.progress(1.0)
            status_info.success(f"🎉 全部完成！成功处理 {result['count']} 个订单")
            
            # 最终统计
            final_usage = result["usage"]
            current_orders_metric.metric("✅ 处理完成", f"{result['count']}/{result.get('total_found', result['count'])}")
            tokens_metric.metric("🔤 Token总消耗", f"{final_usage['tokens_used']:,}")
            cost_metric.metric("💰 本次总成本", f"${final_usage['estimated_cost']:.3f}")
            
            # 庆祝效果
            st.balloons()
            
            # 结果展示
            st.markdown("---")
            
            # 处理统计卡片
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.info(f"**📋 找到订单**\n{result.get('total_found', result['count'])} 个")
            with col2:
                st.success(f"**✅ 成功处理**\n{result['count']} 个")
            with col3:
                st.info(f"**🔤 Token消耗**\n{final_usage['tokens_used']:,}")
            with col4:
                st.info(f"**💰 处理成本**\n${final_usage['estimated_cost']:.3f}")
            
            # 结果链接
            sheet_url = st.secrets.get("app_settings", {}).get("sheet_url",
                "https://docs.google.com/spreadsheets/d/1g_xoXrBy8MnG_76nrRAT9eNaMytE5YrCYBUK3q5AE04")
            
            st.markdown(f"""
            ### 📋 查看翻译结果
            
            **🎉 翻译处理完成！** 所有结果已保存到工作表中。
            
            [🔗 点击查看完整结果表格]({sheet_url})
            
            **📊 输出内容说明：**
            - **Review Date** - 审核日期（原始数据）
            - **Order ID** - 订单编号（原始数据）
            - **Review Details** - 审核详情（英文翻译）
            - **UW Instructions** - UW指令（根据电核需求智能格式化）
            - **Processing Date** - 处理日期（今天）
            
            **💡 提示：** 可以直接复制表格内容到其他系统中使用
            """)
            
        else:
            # 处理失败
            progress_bar.progress(0)
            status_info.error(f"❌ 处理失败")
            
            st.error(f"**处理失败：** {result['message']}")
            
            # 故障排除建议
            with st.expander("🔧 故障排除建议"):
                st.markdown("""
                **常见问题及解决方法：**
                
                1. **找不到订单数据**
                   - 检查选择的日期范围是否正确
                   - 确认表格中有对应日期的数据
                   
                2. **找不到必要的列**
                   - 检查表格列名是否为：审核日期、订单编号、是否需要电核等
                   - 确认表格结构没有变化
                   
                3. **API调用失败**
                   - 检查OpenAI API密钥是否有效
                   - 确认账户余额充足
                   
                4. **权限问题**
                   - 确认Google Sheets已分享给服务账号
                   - 检查服务账号是否有编辑权限
                   
                5. **超出限制**
                   - 订单数量可能超过每日处理限制
                   - 尝试缩小日期范围或联系管理员
                """)
                
            # 重试按钮
            if st.button("🔄 重试处理", type="secondary"):
                st.rerun()

# 侧边栏
with st.sidebar:
    st.markdown("### ℹ️ 使用指南")
    st.markdown("""
    **🚀 使用步骤:**
    1. 选择日期范围
    2. 点击开始处理
    3. 等待处理完成
    4. 查看翻译结果
    
    **✨ 特点:**
    - 零配置使用
    - 自动格式识别
    - 实时进度显示
    - 成本统计
    """)
    
    # 格式说明
    if st.button("📖 查看输出格式"):
        st.markdown("""
        **需要电核订单:**
        ```
        ═══ THE APPROVAL RESULT... ═══
        ═══ NEED TO CALL... ═══
        [翻译内容]
        ═══ REVIEW ADVICE ═══
        [信审意见]
        ```
        
        **不需要电核订单:**
        ```
        ═══ THE APPROVAL RESULT... ═══
        [翻译内容]
        ═══ REVIEW ADVICE ═══
        [信审意见]
        ```
        """)

if __name__ == "__main__":
    main()
