import io
import fitz  # PyMuPDF
import streamlit as st
import os
import shutil
import zipfile
import streamlit.components.v1 as components

fitz.TOOLS.mupdf_display_errors(False)

st.set_page_config(page_title="PDF Page Remover", layout="centered")
st.title("📄 Custom PDF Page Remover")
st.write("Upload your PDF or ZIP files to strip unwanted pages from the front or back.")

# --- AUTOMATED PWA INJECTION LOGIC ---
try:
    streamlit_static_path = os.path.join(os.path.dirname(st.__file__), "static")
    manifest_dest = os.path.join(streamlit_static_path, "manifest.json")
    sw_dest = os.path.join(streamlit_static_path, "sw.js")

    if not os.path.exists(manifest_dest):
        shutil.copy("pwa/manifest.json", manifest_dest)
    if not os.path.exists(sw_dest):
        shutil.copy("pwa/sw.js", sw_dest)
except Exception:
    pass

pwa_html = """
<script>
    var link = window.parent.document.createElement('link');
    link.rel = 'manifest';
    link.href = './manifest.json';
    window.parent.document.getElementsByTagName('head')[0].appendChild(link);

    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('./sw.js')
    }
</script>
"""
components.html(pwa_html, height=0, width=0)

# --- Sidebar Configuration ---
st.sidebar.header("Page Removal Settings")
st.sidebar.write("Specify how many pages to remove from each PDF.")

remove_front = st.sidebar.number_input("Pages to remove from FRONT:", min_value=0, value=0, step=1)
remove_back = st.sidebar.number_input("Pages to remove from BACK:", min_value=0, value=0, step=1)

if remove_front == 0 and remove_back == 0:
    st.warning("⚠️ No page removal set. Output PDFs will be identical to the originals.")

# --- ZIP Helper Functions ---
@st.cache_data
def parse_zip(f_bytes):
    z_contents = {}
    with zipfile.ZipFile(io.BytesIO(f_bytes)) as z:
        for f in z.namelist():
            z_contents[f] = z.read(f)
    return z_contents

def build_tree(paths):
    tree = {}
    for path in paths:
        if path.endswith('/'):
            continue  
        parts = path.split('/')
        curr = tree
        for part in parts[:-1]:
            if part not in curr:
                curr[part] = {}
            curr = curr[part]
        curr[parts[-1]] = path
    return tree

def get_all_files(node):
    files = []
    for k, v in node.items():
        if isinstance(v, dict):
            files.extend(get_all_files(v))
        else:
            files.append(v)
    return files

def toggle_folder(folder_key, child_files, z_id):
    state = st.session_state[folder_key]
    for f in child_files:
        st.session_state[f"file_{z_id}_{f}"] = state

def render_tree(node, z_id, current_path=""):
    for key, val in node.items():
        if isinstance(val, dict):
            folder_path = f"{current_path}/{key}" if current_path else key
            with st.expander(f"📁 {key}", expanded=True):
                all_children = get_all_files(val)
                folder_key = f"folder_{z_id}_{folder_path}"
                
                if folder_key not in st.session_state:
                    st.session_state[folder_key] = True

                st.checkbox(
                    f"Select all in {key}", 
                    key=folder_key, 
                    on_change=toggle_folder, 
                    args=(folder_key, all_children, z_id)
                )
                render_tree(val, z_id, folder_path)
        else:
            file_key = f"file_{z_id}_{val}"
            if file_key not in st.session_state:
                st.session_state[file_key] = True
            
            if val.lower().endswith('.pdf'):
                st.checkbox(f"📄 {key}", key=file_key)
            else:
                st.checkbox(f"📄 {key} (Will be copied as-is)", key=file_key, disabled=True)

# --- Core PDF Processing Function ---
def process_pdf_pages(file_bytes, rm_front, rm_back):
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    total_pages = doc.page_count
    
    if total_pages == 0:
        doc.close()
        return file_bytes

    start_idx = rm_front
    end_idx = total_pages - rm_back
    
    if start_idx >= end_idx or start_idx >= total_pages:
        doc.close()
        return None
        
    pages_to_keep = list(range(start_idx, end_idx))
    doc.select(pages_to_keep)
    
    out_buffer = io.BytesIO()
    doc.save(out_buffer, garbage=3, deflate=True)
    doc.close()
    return out_buffer.getvalue()

# --- Main File Uploader ---
uploaded_files = st.file_uploader(
    "Choose PDF or ZIP files", type=["pdf", "zip"], accept_multiple_files=True
)

if uploaded_files:
    st.write(f"### Processing {len(uploaded_files)} file(s):")

    for uploaded_file in uploaded_files:
        file_bytes = uploaded_file.read()
        
        # --- ZIP FILE PROCESSING ---
        if uploaded_file.name.lower().endswith('.zip'):
            st.write("---")
            st.write(f"#### 📦 {uploaded_file.name}")
            
            zip_contents = parse_zip(file_bytes)
            zip_id = uploaded_file.file_id
            tree = build_tree(zip_contents.keys())
            
            st.write("**Select the PDFs you want to modify. Unchecked PDFs and non-PDFs will be copied identically.**")
            render_tree(tree, zip_id)

            btn_col, dl_col = st.columns([1, 1])
            
            with btn_col:
                process_clicked = st.button(f"⚙️ Process ZIP", key=f"btn_proc_{zip_id}")

            if process_clicked:
                st.session_state[f"processed_data_{zip_id}"] = None 
                with st.spinner("Processing files and rebuilding ZIP..."):
                    output_zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(output_zip_buffer, 'w', zipfile.ZIP_DEFLATED) as out_zip:
                        for path, content in zip_contents.items():
                            
                            if path.endswith('/'):
                                out_zip.writestr(path, content)
                                continue

                            file_key = f"file_{zip_id}_{path}"
                            is_checked = st.session_state.get(file_key, True)
                            
                            if is_checked and path.lower().endswith('.pdf'):
                                try:
                                    processed_bytes = process_pdf_pages(content, remove_front, remove_back)
                                    if processed_bytes:
                                        out_zip.writestr(path, processed_bytes)
                                    else:
                                        st.warning(f"Skipped `{path}`: Requested removal exceeds total pages.")
                                except Exception:
                                    out_zip.writestr(path, content)
                            else:
                                out_zip.writestr(path, content)
                                
                    st.session_state[f"processed_data_{zip_id}"] = output_zip_buffer.getvalue()
                    
            if st.session_state.get(f"processed_data_{zip_id}"):
                with dl_col:
                    st.download_button(
                        label=f"📥 Download Processed ZIP",
                        data=st.session_state[f"processed_data_{zip_id}"],
                        file_name=f"trimmed_{uploaded_file.name}",
                        mime="application/zip",
                        key=f"dl_{zip_id}",
                    )

        # --- ORIGINAL PDF PROCESSING ---
        elif uploaded_file.name.lower().endswith('.pdf'):
            st.write("---")
            try:
                processed_bytes = process_pdf_pages(file_bytes, remove_front, remove_back)
                
                col1, col2 = st.columns([3, 1])
                with col1:
                    if processed_bytes:
                        st.success(f"**{uploaded_file.name}** — Pages removed successfully.")
                    else:
                        st.error(f"**{uploaded_file.name}** — Cannot remove {remove_front + remove_back} pages from this document.")
                
                if processed_bytes:
                    with col2:
                        st.download_button(
                            label="📥 Download",
                            data=processed_bytes,
                            file_name=f"trimmed_{uploaded_file.name}",
                            mime="application/pdf",
                            key=uploaded_file.name,
                        )
            except Exception as e:
                st.error(f"Failed to process **{uploaded_file.name}**. Error: {e}")
