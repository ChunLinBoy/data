import streamlit as st
import pandas as pd
import zipfile
import io
import datetime

# --- 网页基本配置 ---
st.set_page_config(page_title="CSV 批量过滤与合并工具", layout="centered")
st.title("📁 CSV/ZIP 批量合并与日期过滤")
st.write("支持上传多个 CSV 文件或 **ZIP 压缩包**，自动检测编码并根据指定日期过滤合并数据。")

# --- 核心修复：初始化 Session State 缓存 ---
# 用来保存处理结果，防止点击下载按钮后页面刷新导致数据丢失
if 'processed_csv' not in st.session_state:
    st.session_state.processed_csv = None
    st.session_state.output_filename = ""
    st.session_state.result_msg = ""
    st.session_state.result_status = "" # 'success' 或 'error'

# --- 1. 自定义时间选择器 ---
st.subheader("1. 选择需要过滤的时间范围")
default_start = datetime.date(2026, 7, 1)
default_end = datetime.date(2026, 7, 31)

start_date = st.date_input("开始日期", default_start)
end_date = st.date_input("结束日期", default_end)

if start_date > end_date:
    st.error("❌ 错误：开始日期不能晚于结束日期，请重新选择！")

# --- 2. 文件上传组件 ---
st.subheader("2. 上传文件")
uploaded_files = st.file_uploader(
    "请选择 CSV 文件或 ZIP 压缩包 (支持多选及混合上传)", 
    type=['csv', 'zip'], 
    accept_multiple_files=True
)

def process_csv_bytes(file_bytes, display_name, start_ts, end_ts):
    """完美复刻本地 1.py 的严格编码检测逻辑"""
    encodings_to_try = ['utf-8', 'gbk', 'gb18030', 'utf-8-sig', 'latin1']
    df = None
    
    # 循环尝试不同的编码
    for encoding in encodings_to_try:
        try:
            # 严格读取，绝不使用 encoding_errors='replace' 吞噬报错
            df = pd.read_csv(io.BytesIO(file_bytes), encoding=encoding)
            break # 只有在完全没有乱码报错的情况下，才会跳出循环
        except (UnicodeDecodeError, LookupError):
            continue # 只要报错，立刻换下一个编码
            
    if df is None:
        st.warning(f"❌ 读取失败 {display_name}: 无法识别文件编码，已跳过。")
        return None

    try:
        # 清理列名两端的空格
        df.columns = df.columns.str.strip()
        
        # 检查是否存在 'Date' 列
        if 'Date' in df.columns:
            df['Date_Parsed'] = pd.to_datetime(df['Date'], errors='coerce')
            
            # 根据用户选择的时间进行过滤
            mask = (df['Date_Parsed'] >= start_ts) & (df['Date_Parsed'] <= end_ts)
            filtered_df = df.loc[mask].copy()
            
            if not filtered_df.empty:
                filtered_df['Source_File'] = display_name
                filtered_df = filtered_df.drop(columns=['Date_Parsed']) 
                return filtered_df
        else:
            st.warning(f"⚠️ {display_name} 中未找到 'Date' 列，已跳过。")
    except Exception as e:
        st.error(f"处理 {display_name} 内容时出错: {e}")
    return None


# --- 3. 开始处理按钮逻辑 ---
if uploaded_files and start_date <= end_date:
    if st.button("🚀 开始处理并合并数据"):
        data_frames = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        total_files = len(uploaded_files)
        
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        
        for i, file in enumerate(uploaded_files):
            status_text.text(f"正在读取文件: {file.name}...")
            file_bytes = file.read()
            
            # 处理 ZIP 压缩包
            if file.name.endswith('.zip'):
                try:
                    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                        for member in z.namelist():
                            if member.endswith('.csv') and not member.startswith('__MACOSX'):
                                member_bytes = z.read(member)
                                display_name = f"{file.name} -> {member.split('/')[-1]}"
                                filtered_df = process_csv_bytes(member_bytes, display_name, start_ts, end_ts)
                                if filtered_df is not None:
                                    data_frames.append(filtered_df)
                except Exception as e:
                    st.error(f"解压 {file.name} 失败: {e}")
            
            # 处理单独的 CSV 文件
            elif file.name.endswith('.csv'):
                filtered_df = process_csv_bytes(file_bytes, file.name, start_ts, end_ts)
                if filtered_df is not None:
                    data_frames.append(filtered_df)
            
            progress_bar.progress((i + 1) / total_files)
        
        status_text.text("扫描完成，正在生成结果...")
        
        # 将结果存入 session_state
