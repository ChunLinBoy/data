import streamlit as st
import pandas as pd
import zipfile
import io
import datetime

# --- 网页基本配置 ---
st.set_page_config(page_title="CSV 批量过滤与合并工具", layout="centered")
st.title("📁 数据批量合并与达人筛选工具")
st.write("支持上传数据文件，根据【指定日期】和【达人名单】双重过滤并合并数据。")

# 初始化 Session State 缓存
if 'processed_csv' not in st.session_state:
    st.session_state.processed_csv = None
    st.session_state.output_filename = ""
    st.session_state.result_msg = ""
    st.session_state.result_status = "" 
    # 正向数据缓存
    st.session_state.total_clicks = 0
    st.session_state.total_orders = 0
    st.session_state.total_sales = 0.0
    # 负向（退货）数据缓存
    st.session_state.total_return_orders = 0
    st.session_state.total_return_sales = 0.0

# --- 1. 自定义时间选择器 ---
st.subheader("1. 选择需要过滤的时间范围")
col1, col2 = st.columns(2)
with col1:
    default_start = datetime.date(2026, 7, 1)
    start_date = st.date_input("开始日期", default_start)
with col2:
    default_end = datetime.date(2026, 7, 31)
    end_date = st.date_input("结束日期", default_end)

if start_date > end_date:
    st.error("❌ 错误：开始日期不能晚于结束日期，请重新选择！")

# --- 2. 达人白名单上传 ---
st.subheader("2. 上传达人筛选名单 (可选)")
st.write("请上传包含 `amazon id` 列的文件（支持 CSV 或 Excel）。**如果不上传，系统将跳过达人比对，仅执行日期过滤。**")
whitelist_file = st.file_uploader("选择达人名单文件 (非必填)", type=['csv', 'xlsx'])

valid_creators_set = set()
if whitelist_file:
    try:
        if whitelist_file.name.endswith('.csv'):
            wl_df = None
            for enc in ['utf-8-sig', 'gbk', 'utf-8', 'gb18030']:
                try:
                    whitelist_file.seek(0)
                    wl_df = pd.read_csv(whitelist_file, encoding=enc)
                    break
                except Exception:
                    continue
            if wl_df is None:
                st.error("❌ 无法识别达人名单的编码格式。")
        else:
            wl_df = pd.read_excel(whitelist_file)
        
        if wl_df is not None:
            wl_df.columns = wl_df.columns.str.strip().str.lower()
            if 'amazon id' in wl_df.columns:
                raw_ids = wl_df['amazon id'].dropna().astype(str).str.strip()
                valid_creators_set = set(raw_ids[raw_ids != ''])
                st.success(f"✅ 成功读取达人名单，共加载了 {len(valid_creators_set)} 个有效 Amazon ID，本次合并将开启双重过滤。")
            else:
                st.error("❌ 在上传的名单中未找到 'amazon id' 列，请检查文件表头！")
    except Exception as e:
        st.error(f"读取达人名单时出错: {e}")

# --- 3. 数据文件上传组件 ---
st.subheader("3. 上传原始数据文件")
uploaded_files = st.file_uploader(
    "请选择包含数据的 CSV 文件或 ZIP 压缩包", 
    type=['csv', 'zip'], 
    accept_multiple_files=True
)

# 核心处理函数
def process_csv_bytes(file_bytes, display_name, start_ts, end_ts, creators_whitelist, log_area):
    encodings_to_try = ['utf-8', 'gbk', 'gb18030', 'utf-8-sig', 'latin1']
    df = None
    
    for encoding in encodings_to_try:
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), encoding=encoding)
            break 
        except (UnicodeDecodeError, LookupError):
            continue 
            
    if df is None:
        log_area.error(f"❌ 读取失败 {display_name}: 无法识别文件编码。")
        return None

    try:
        df.columns = df.columns.str.strip()
        
        # 步骤 A：检查并执行日期过滤
        if 'Date' in df.columns:
            clean_date_str = df['Date'].astype(str).str.strip()
            df['Date_Parsed'] = pd.to_datetime(clean_date_str, format='mixed', errors='coerce')
            mask = (df['Date_Parsed'] >= start_ts) & (df['Date_Parsed'] <= end_ts)
            filtered_df = df.loc[mask].copy()
            
            if filtered_df.empty:
                log_area.caption(f"⚪ 跳过 {display_name}: 日期不符。")
                return None
        else:
            log_area.warning(f"⚠️ 跳过 {display_name}: 未找到 'Date' 列。")
            return None

        # 步骤 B：执行达人名称筛选
        if creators_whitelist:
            creator_col = None
            for col in filtered_df.columns:
                if col.lower() == 'creator name':
                    creator_col = col
                    break
            
            if creator_col:
                mask_creator = filtered_df[creator_col].astype(str).str.strip().isin(creators_whitelist)
                filtered_df = filtered_df.loc[mask_creator].copy()
                
                if filtered_df.empty:
                    log_area.caption(f"⚪ 跳过 {display_name}: 达人未匹配。")
                    return None
            else:
                log_area.warning(f"⚠️ 跳过 {display_name}: 未找到 'Creator Name' 列。")
                return None

        filtered_df['Source_File'] = display_name
        filtered_df = filtered_df.drop(columns=['Date_Parsed']) 
        
        log_area.success(f"✅ 提取成功: **{display_name}** (找到 **{len(filtered_df)}** 条数据)")
        return filtered_df
        
    except Exception as e:
        log_area.error(f"❌ 处理 {display_name} 内容时出错: {e}")
    return None

# --- 4. 开始处理按钮逻辑 ---
if uploaded_files and start_date <= end_date:
    if not valid_creators_set:
        st.info("ℹ️ 尚未上传达人名单，系统将仅进行【日期过滤】。")

    if st.button("🚀 开始处理并合并数据"):
        data_frames = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        total_files = len(uploaded_files)
        
        st.markdown("### 📋 详细处理日志")
        log_area = st.expander("点击查看文件扫描详情", expanded=True)
        
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        
        for i, file in enumerate(uploaded_files):
            status_text.text(f"正在处理: {file.name} ({i+1}/{total_files})...")
            file_bytes = file.read()
            
            if file.name.endswith('.zip'):
                try:
                    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                        for member in z.namelist():
                            if member.endswith('.csv') and not member.startswith('__MACOSX'):
                                member_bytes = z.read(member)
                                display_name = f"{file.name} -> {member.split('/')[-1]}"
                                filtered_df = process_csv_bytes(
                                    member_bytes, display_name, start_ts, end_ts, valid_creators_set, log_area
                                )
                                if filtered_df is not None:
                                    data_frames.append(filtered_df)
                except Exception as e:
                    log_area.error(f"❌ 解压 {file.name} 失败: {e}")
            elif file.name.endswith('.csv'):
                filtered_df = process_csv_bytes(
                    file_bytes, file.name, start_ts, end_ts, valid_creators_set, log_area
                )
                if filtered_df is not None:
                    data_frames.append(filtered_df)
            
            progress_bar.progress((i + 1) / total_files)
        
        status_text.text("扫描完成，正在生成结果...")
        
        if data_frames:
            final_combined_df = pd.concat(data_frames, ignore_index=True)
            
            # === 数据格式清理 ===
            summary_cols = ['Clicks', 'Orders', 'Sales']
            for col in summary_cols:
                if col in final_combined_df.columns:
                    cleaned_col = final_combined_df[col].astype(str).str.replace(r'[^\d.-]', '', regex=True)
                    final_combined_df[col] = pd.to_numeric(cleaned_col, errors='coerce').fillna(0)
                else:
                    final_combined_df[col] = 0
            
            # === 分别计算正向数据与负向（退货）数据 ===
            # 正数汇总（实际产生的量）
            st.session_state.total_clicks = int(final_combined_df.loc[final_combined_df['Clicks'] > 0, 'Clicks'].sum())
            st.session_state.total_orders = int(final_combined_df.loc[final_combined_df['Orders'] > 0, 'Orders'].sum())
            st.session_state.total_sales = float(final_combined_df.loc[final_combined_df['Sales'] > 0, 'Sales'].sum())
            
            # 负数汇总（退货量）。使用 abs() 取绝对值，转为正数方便直观展示
            st.session_state.total_return_orders = int(abs(final_combined_df.loc[final_combined_df['Orders'] < 0, 'Orders'].sum()))
            st.session_state.total_return_sales = float(abs(final_combined_df.loc[final_combined_df['Sales'] < 0, 'Sales'].sum()))
            # ============================================

            csv_str = final_combined_df.to_csv(index=False)
            st.session_state.processed_csv = csv_str.encode('utf-8-sig')
            
            st.session_state.output_filename = f"Filtered_Data_{start_date.strftime('%m%d')}-{end_date.strftime('%m%d')}.csv"
            st.session_state.result_msg = f"🎉 处理完成！符合条件的数据共计： {len(final_combined_df)} 条。"
            st.session_state.result_status = 'success'
        else:
            st.session_state.processed_csv = None
            st.session_state.result_msg = f"❌ 未找到符合所有条件（日期范围内且在达人名单中）的数据。"
            st.session_state.result_status = 'error'

# --- 5. 结果展示与下载 ---
if st.session_state.result_status == 'success':
    st.success(st.session_state.result_msg)
    
    st.subheader("📊 核心数据汇总")
    
    # 将仪表盘分成两排，更清晰
    st.markdown("##### 📈 正向业绩")
    metric_col1, metric_col2, metric_col3 = st.columns(3)
    metric_col1.metric("总点击量 (Clicks)", f"{st.session_state.total_clicks:,}")
    metric_col2.metric("总订单数 (Orders)", f"{st.session_state.total_orders:,}")
    metric_col3.metric("总销售额 (Sales)", f"${st.session_state.total_sales:,.2f}")
    
    st.markdown("##### 📉 退款/退货数据")
    ret_col1, ret_col2, ret_col3 = st.columns(3)
    # 第一列通常退货不看点击，所以只展示订单和金额
    ret_col1.metric("总退货单数 (Return Orders)", f"{st.session_state.total_return_orders:,}")
    ret_col2.metric("总退货金额 (Return Sales)", f"${st.session_state.total_return_sales:,.2f}")
    
    st.write("---")
    
    st.download_button(
        label="⬇️ 下载最终合并后的 CSV 文件",
        data=st.session_state.processed_csv,
        file_name=st.session_state.output_filename,
        mime="text/csv"
    )
elif st.session_state.result_status == 'error':
    st.error(st.session_state.result_msg)
