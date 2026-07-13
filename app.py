import streamlit as st
import pandas as pd
import zipfile
import io
import datetime

# 网页基本配置
st.set_page_config(page_title="CSV 批量过滤与合并工具", layout="centered")
st.title("📁 CSV/ZIP 批量合并与自定义日期过滤")
st.write("支持上传多个 CSV 文件或 **ZIP 压缩包**，解压后自动根据您指定的日期范围过滤并合并数据。")

# 1. 自定义时间选择器
st.subheader("1. 选择需要过滤的时间范围")
# 设置默认的起始和结束时间
default_start = datetime.date(2026, 7, 1)
default_end = datetime.date(2026, 7, 31)

start_date = st.date_input("开始日期", default_start)
end_date = st.date_input("结束日期", default_end)

if start_date > end_date:
    st.error("❌ 错误：开始日期不能晚于结束日期，请重新选择！")

# 2. 文件上传组件 (增加了对 zip 的支持)
st.subheader("2. 上传文件")
uploaded_files = st.file_uploader(
    "请选择 CSV 文件或 ZIP 压缩包 (支持多选及混合上传)", 
    type=['csv', 'zip'], 
    accept_multiple_files=True
)

# 核心数据处理函数
def process_csv_bytes(file_bytes, display_name, start_ts, end_ts):
    """尝试不同编码读取二进制 CSV 数据并进行日期过滤"""
    encodings_to_try = ['utf-8', 'gbk', 'gb18030', 'utf-8-sig', 'latin1']
    df = None
    
    for encoding in encodings_to_try:
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), encoding=encoding)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    
    if df is None:
        st.warning(f"❌ 读取失败 {display_name}: 无法识别文件编码，已跳过。")
        return None

    try:
        df.columns = df.columns.str.strip()
        if 'Date' in df.columns:
            df['Date_Parsed'] = pd.to_datetime(df['Date'], errors='coerce')
            
            # 根据用户选择的动态时间范围进行过滤
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


# 3. 开始处理按钮逻辑
if uploaded_files and start_date <= end_date:
    if st.button("🚀 开始处理并合并数据"):
        data_frames = []
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        total_files = len(uploaded_files)
        
        # 将选择的日期转换为 Pandas 的 Timestamp 格式以便准确比对
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        
        for i, file in enumerate(uploaded_files):
            status_text.text(f"正在读取文件: {file.name}...")
            file_bytes = file.read()
            
            # 情况 A: 如果上传的是 ZIP 压缩包
            if file.name.endswith('.zip'):
                try:
                    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                        for member in z.namelist():
                            # 过滤掉 Mac 系统自带的缓存隐藏文件，并且只处理 .csv 结尾的文件
                            if member.endswith('.csv') and not member.startswith('__MACOSX'):
                                member_bytes = z.read(member)
                                # 提取纯文件名以供记录来源
                                short_name = member.split('/')[-1]
                                display_name = f"{file.name} -> {short_name}"
                                
                                filtered_df = process_csv_bytes(member_bytes, display_name, start_ts, end_ts)
                                if filtered_df is not None:
                                    data_frames.append(filtered_df)
                except Exception as e:
                    st.error(f"解压 {file.name} 失败，可能文件已损坏: {e}")
            
            # 情况 B: 如果直接上传的是单独的 CSV 文件
            elif file.name.endswith('.csv'):
                filtered_df = process_csv_bytes(file_bytes, file.name, start_ts, end_ts)
                if filtered_df is not None:
                    data_frames.append(filtered_df)
            
            # 更新进度条
            progress_bar.progress((i + 1) / total_files)
        
        status_text.text("所有文件扫描完成，正在打包结果...")
        
        # 4. 导出与下载
        if data_frames:
            final_combined_df = pd.concat(data_frames, ignore_index=True)
            csv_buffer = final_combined_df.to_csv(index=False, encoding='utf-8-sig')
            
            st.success(f"🎉 处理完成！在选定范围内共成功合并了 {len(final_combined_df)} 条数据。")
            
            # 根据用户选择的时间动态命名导出的文件名
            output_filename = f"Combined_Data_{start_date.strftime('%Y%m%d')}_to_{end_date.strftime('%Y%m%d')}.csv"
            
            st.download_button(
                label="⬇️ 下载合并后的 CSV 文件",
                data=csv_buffer,
                file_name=output_filename,
                mime="text/csv"
            )
        else:
            st.error(f"❌ 处理完成。但在上传的文件/压缩包中，均未找到符合 {start_date} 至 {end_date} 范围内的数据。")
