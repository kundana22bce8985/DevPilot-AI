"""DevPilot dashboard: local integrated workflow and read-only uploaded analysis."""
import difflib
import hashlib
import io
import re
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

import streamlit as st
from github_analyzer import show_github_analyzer, analyze_code
from uploaded_workflow import run_uploaded_workflow

# Keep the full integrated MCP/pgvector workflow on the Windows development machine.
# Streamlit Community Cloud runs on Linux and hosts the read-only AI demo.
IS_CLOUD_DEMO = sys.platform != "win32"

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR / 'bug_demo'
ENGINE_FILE = BASE_DIR / 'devpilot_integrated.py'
SOURCE_FILE = PROJECT_DIR / 'calculator.py'
LOCAL_OPTION = 'Local: bug_demo'
UPLOAD_OPTION = 'Upload Project'
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_FILE_BYTES = 100_000
MAX_FILES = 500
MAX_ARCHIVE_ENTRIES = 5000
MAX_TOTAL_SOURCE = 10 * 1024 * 1024

st.set_page_config(page_title='DevPilot AI', page_icon='🤖', layout='wide', initial_sidebar_state='expanded')
st.markdown('''<style>
.stApp {background:#0b1120;color:#e5e7eb}
.block-container {padding-top:2.5rem;max-width:1450px}
[data-testid="stSidebar"] {background:#111827;border-right:1px solid #334155}
[data-testid="stSidebar"] p,[data-testid="stSidebar"] label,[data-testid="stSidebar"] span {color:#e2e8f0!important}
h1,h2,h3 {color:#f8fafc!important}
.hero {background:linear-gradient(120deg,#172554,#111827);border:1px solid #334155;border-radius:16px;padding:26px;margin-bottom:25px}
.hero-title {font-size:32px;font-weight:800;color:white}
.hero-subtitle {color:#cbd5e1;margin-top:8px}
.agent-card {background:#111c30;border:1px solid #334155;border-radius:12px;padding:18px;margin-bottom:12px}
.agent-name {font-weight:700;color:white}
.agent-desc {color:#cbd5e1;font-size:13px;margin-top:6px}
[data-testid="stMetric"] {background:#111c30;border:1px solid #334155;border-radius:12px;padding:15px}
[data-testid="stMetricLabel"] p {color:#cbd5e1!important}
[data-testid="stMetricValue"] {color:#f8fafc!important}
div.stButton>button[kind="primary"] {background:#2563eb;color:white;border-radius:10px;font-weight:700}
</style>''', unsafe_allow_html=True)

for key, value in {
    'result': None, 'github_repo': None, 'github_analysis': None,
    'uploaded_project': None, 'uploaded_analysis': None,
    'uploaded_workflow_result': None, 'selected_project': LOCAL_OPTION,
}.items():
    if key not in st.session_state:
        st.session_state[key] = value


def read_source():
    return SOURCE_FILE.read_text(encoding='utf-8') if SOURCE_FILE.exists() else 'Source file not found.'


def section(output, start, end=None):
    match = re.search(start, output, flags=re.IGNORECASE)
    if not match:
        return ''
    value = output[match.end():]
    if end:
        ending = re.search(end, value, flags=re.IGNORECASE)
        if ending:
            value = value[:ending.start()]
    return value.strip()


def extract_code(output):
    return section(output, r'Gemini generated code:\s*', r'\n\s*6\.\s*REVIEWER AGENT').strip().strip('`')


def extract_plan(output):
    return section(output, r'Gemini Plan:\s*', r'\n\s*5\.\s*GEMINI CODER AGENT')


def extract_review(output):
    matches = re.findall(r'Review decision:\s*(APPROVED|REJECTED)', output, re.IGNORECASE)
    return matches[-1].upper() if matches else 'UNKNOWN'


def extract_tests(output, final=False):
    block = (section(output, r'6\.\s*REVIEWER AGENT', r'DEV PILOT FINAL OUTPUT')
             if final else section(output, r'3\.\s*TEST RUNNER MCP', r'4\.\s*GEMINI PLANNER AGENT'))
    def number(label):
        match = re.search(rf'\b{label}:\s*(\d+)', block, re.IGNORECASE)
        return int(match.group(1)) if match else 0
    return {'passed': number('Passed'), 'failed': number('Failed'), 'total': number('Total')}


def make_diff(original, fixed, filename):
    return '\n'.join(difflib.unified_diff(original.splitlines(), fixed.splitlines(),
                    fromfile='original/' + filename, tofile='proposed/' + filename, lineterm=''))


def agent_card(name, description, emoji):
    # Text is escaped to avoid injecting HTML if labels are ever dynamic.
    from html import escape
    st.markdown(f'<div class="agent-card"><div class="agent-name">{escape(emoji)} {escape(name)}</div>'
                f'<div class="agent-desc">{escape(description)}</div></div>', unsafe_allow_html=True)


def load_project_files(uploaded_files):
    python_files = {}
    total_source = 0
    for uploaded in uploaded_files:
        name = Path(uploaded.name).name
        if uploaded.size > MAX_UPLOAD_BYTES:
            raise ValueError(f'{name} exceeds the 15 MB upload limit.')
        raw = uploaded.getvalue()
        if name.lower().endswith('.py'):
            if len(raw) > MAX_FILE_BYTES:
                raise ValueError(f'{name} exceeds 100 KB.')
            if name in python_files:
                raise ValueError(f'Duplicate filename: {name}')
            python_files[name] = raw.decode('utf-8')
            total_source += len(raw)
        elif name.lower().endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_ARCHIVE_ENTRIES:
                    raise ValueError('ZIP contains too many entries.')
                for entry in entries:
                    filename = entry.filename
                    parts = filename.split('/')
                    if entry.is_dir() or filename.startswith('/') or '\\' in filename or '..' in parts:
                        continue
                    file_type = (entry.external_attr >> 16) & 0o170000
                    if file_type == 0o120000 or not filename.lower().endswith('.py'):
                        continue
                    if any(part in {'.venv','venv','__pycache__','site-packages','.git'} for part in parts):
                        continue
                    if entry.file_size > MAX_FILE_BYTES:
                        continue
                    if filename in python_files:
                        raise ValueError(f'Duplicate filename: {filename}')
                    if len(python_files) >= MAX_FILES:
                        raise ValueError('Too many Python files.')
                    with archive.open(entry) as source:
                        content = source.read(MAX_FILE_BYTES + 1)
                    if len(content) > MAX_FILE_BYTES:
                        continue
                    python_files[filename] = content.decode('utf-8')
                    total_source += len(content)
                    if total_source > MAX_TOTAL_SOURCE:
                        raise ValueError('Project source exceeds 10 MB.')
        else:
            raise ValueError('Only ZIP and Python files are supported.')
        if len(python_files) > MAX_FILES or total_source > MAX_TOTAL_SOURCE:
            raise ValueError('Project exceeds file or size limits.')
    return python_files


def file_fingerprint(filename, code):
    return hashlib.sha256((filename + '\0' + code).encode('utf-8')).hexdigest()


with st.sidebar:
    st.title('🤖 DevPilot AI')
    st.caption('Agentic Codebase Assistant')
    st.divider()
    page = st.radio('Navigation', ['Dashboard','GitHub Analyzer','Upload Project',
                                   'Code Comparison','Agent Workflow','Execution Logs'])
    st.divider()
    st.subheader('Project')
    github_repo = st.session_state.github_repo
    options = [LOCAL_OPTION, UPLOAD_OPTION]
    if github_repo:
        options.append(f"GitHub: {github_repo['name']}")
    if st.session_state.selected_project not in options:
        st.session_state.selected_project = LOCAL_OPTION
    selected_project = st.selectbox('Select Project', options, key='selected_project')
    if selected_project == UPLOAD_OPTION:
        st.info('Uploaded project selected — static analysis only')
    elif selected_project.startswith('GitHub:'):
        st.success('GitHub repository selected — static analysis only')
    else:
        st.info('Trusted local demo selected')
    st.divider()
    st.subheader('Technology Stack')
    st.write('🐍 Python · 🧠 Gemini · 🔗 LangGraph')
    st.write('🛠️ MCP · 🧪 Pytest · 🌐 Streamlit')
    st.write('🗄️ PostgreSQL + pgvector · 🌳 Tree-sitter')
    st.write('🐙 GitHub')

if selected_project == UPLOAD_OPTION:
    uploaded = st.session_state.uploaded_project
    current_name = uploaded['name'] if uploaded else 'Not uploaded'
    current_source = 'Upload'
    current_count = len(uploaded['files']) if uploaded else 0
elif selected_project.startswith('GitHub:') and github_repo:
    current_name = github_repo['name']
    current_source = 'GitHub'
    current_count = len(github_repo['files'])
else:
    current_name = 'bug_demo'
    current_source = 'Local'
    current_count = len(list(PROJECT_DIR.rglob('*.py'))) if PROJECT_DIR.exists() else 0

st.markdown('''<div class="hero"><div class="hero-title">🚀 DevPilot AI Dashboard</div>
<div class="hero-subtitle">pgvector Retrieval • MCP Tools • LangGraph Agents • Gemini Fixes • Test Validation</div></div>''',
unsafe_allow_html=True)

if page == 'Dashboard':
    st.subheader('Project Overview')
    c1,c2,c3,c4 = st.columns(4)
    c1.metric('Project',current_name)
    c2.metric('Source',current_source)
    c3.metric('Python Files',current_count)
    c4.metric('Local Workflow Stages',7)
    st.divider()
    st.subheader('Integrated AI Agent System')
    a,b,c = st.columns(3)
    with a:
        agent_card('pgvector Retrieval','Retrieves indexed code relevant to the bug','🗄️')
        agent_card('Code Search MCP','Reads trusted local project files','🔍')
        agent_card('Git MCP','Checks local repository status','🌿')
    with b:
        agent_card('Test Runner MCP','Runs tests for the trusted local demo','🧪')
        agent_card('Gemini Planner','Analyzes failures and plans a fix','🧠')
    with c:
        agent_card('Gemini Coder','Generates a proposed corrected file','💻')
        agent_card('Reviewer','Tests proposed changes in a temporary copy','✅')
    st.divider()
    st.subheader('Local DevPilot Workflow')
    st.info('Runs the verified integrated backend on trusted local bug_demo only. '
            'Uploaded/GitHub projects use separate read-only analysis.')
    if IS_CLOUD_DEMO:
        st.info(
            'Full MCP + pgvector test execution is available in the local Windows version. '
            'On this hosted demo, use GitHub Analyzer or Upload Project for AI analysis '
            'and proposed code fixes. Uploaded code is not executed.'
        )

    if st.button(
        '🚀 Run Integrated DevPilot Analysis',
        type='primary',
        use_container_width=True,
        disabled=IS_CLOUD_DEMO,
    ):
        if not ENGINE_FILE.is_file():
            st.error('devpilot_integrated.py not found.')
        elif not PROJECT_DIR.is_dir():
            st.error('bug_demo folder not found.')
        else:
            with st.spinner('Running pgvector, MCP and Gemini agents...'):
                try:
                    started = time.time()
                    original = read_source()
                    run = subprocess.run([sys.executable,'-u',str(ENGINE_FILE)],cwd=str(BASE_DIR),
                                         capture_output=True,text=True,timeout=240,errors='replace')
                    output = run.stdout or ''
                    review = extract_review(output)
                    initial_tests = extract_tests(output)
                    final_tests = extract_tests(output,final=True)
                    approved = (run.returncode == 0 and review == 'APPROVED' and
                                final_tests['total'] > 0 and final_tests['failed'] == 0 and
                                final_tests['passed'] == final_tests['total'])
                    st.session_state.result = {
                        'stdout':output,'stderr':run.stderr or '', 'returncode':run.returncode,
                        'original':original,'fixed':extract_code(output),'plan':extract_plan(output),
                        'review':review,'approved':approved,'initial_tests':initial_tests,
                        'final_tests':final_tests,
                        'retrieval':section(output,r'Retrieved code context:\s*',r'\n\s*1\.\s*CODE SEARCH MCP'),
                        'elapsed':round(time.time()-started,2),
                        'timestamp':datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    }
                except subprocess.TimeoutExpired:
                    st.error('Local workflow timed out after 240 seconds.')
                except Exception as error:
                    st.error(f'Local workflow failed: {error}')
    data = st.session_state.result
    if data:
        st.divider()
        st.subheader('Latest Local Results')
        a,b,c,d = st.columns(4)
        a.metric('Before: Passed',data['initial_tests']['passed'])
        b.metric('Before: Failed',data['initial_tests']['failed'])
        c.metric('After: Passed',data['final_tests']['passed'])
        d.metric('After: Failed',data['final_tests']['failed'])
        st.caption(f"Execution time: {data['elapsed']}s · {data['timestamp']}")
        if data['approved']:
            st.success('Reviewer: APPROVED — proposed fix passed all executed tests')
        else:
            st.warning(f"Reviewer: {data['review']} · Process exit code: {data['returncode']}. Check Execution Logs.")
        if data['retrieval']:
            with st.expander('🗄️ Retrieved Code from pgvector',expanded=False):
                st.code(data['retrieval'],language='python')
        if data['plan']:
            st.subheader('Gemini Planner Output')
            st.write(data['plan'])
        if data['fixed']:
            st.subheader('Proposed Fix')
            st.code(data['fixed'],language='python')
            st.download_button('⬇️ Download Proposed Fix',data=data['fixed'],
                               file_name='fixed_calculator.py',mime='text/x-python')

elif page == 'GitHub Analyzer':
    st.info('GitHub repository analysis does not execute downloaded code.')
    show_github_analyzer()

elif page == 'Upload Project':
    st.header('Upload Your Python Project')
    st.write('Select a ZIP project or Python files from Windows File Explorer.')
    uploaded_files = st.file_uploader('Browse project files',type=['zip','py'],
                                      accept_multiple_files=True,help='Select ZIP or Python files.')
    if uploaded_files:
        st.caption(f'{len(uploaded_files)} file(s) selected')
        if st.button('Load Uploaded Project',type='primary'):
            try:
                files = load_project_files(uploaded_files)
                if not files:
                    st.warning('No Python files found.')
                else:
                    st.session_state.uploaded_project = {'name':uploaded_files[0].name,'files':files}
                    st.session_state.uploaded_analysis = None
                    st.session_state.uploaded_workflow_result = None
                    st.session_state.selected_project = UPLOAD_OPTION
                    st.success('Project loaded successfully!')
            except (ValueError,UnicodeDecodeError,zipfile.BadZipFile,RuntimeError) as error:
                st.error(f'Upload failed: {error}')
    project = st.session_state.uploaded_project
    if project:
        st.divider()
        st.subheader(project['name'])
        files = project['files']
        st.metric('Python Files Loaded',len(files))
        selected_file = st.selectbox('Select Python File',sorted(files.keys()))
        code = files[selected_file]
        fingerprint = file_fingerprint(selected_file,code)
        st.subheader('Original Source Code')
        st.code(code,language='python')
        st.divider()
        st.subheader('Gemini Code Analysis')
        if st.button('Analyze Uploaded File with Gemini',key='analyze_uploaded'):
            try:
                with st.spinner('Gemini is analyzing the file...'):
                    analysis = analyze_code(code,selected_file)
                st.session_state.uploaded_analysis = {'fingerprint':fingerprint,'text':analysis}
            except Exception as error:
                st.error(str(error))
        saved_analysis = st.session_state.uploaded_analysis
        if saved_analysis and saved_analysis['fingerprint'] == fingerprint:
            st.markdown(saved_analysis['text'])
        st.divider()
        st.subheader('LangGraph AI Bug Fixing')
        st.write('Planner Agent → Gemini Coder Agent → Static Reviewer')
        st.warning('Uploaded-project workflow does not execute tests or MCP commands. '
                   'It generates a proposed fix and checks Python syntax only.')
        if st.button('🚀 Run DevPilot LangGraph Agents',type='primary',
                     use_container_width=True,key='run_uploaded_agents'):
            try:
                with st.spinner('Planner, Coder and Reviewer agents are working...'):
                    workflow_result = run_uploaded_workflow(selected_file,code)
                st.session_state.uploaded_workflow_result = {
                    'fingerprint':fingerprint,'result':workflow_result}
                st.success('LangGraph workflow completed!')
            except Exception as error:
                st.error(f'Agent workflow failed: {error}')
        saved_workflow = st.session_state.uploaded_workflow_result
        if saved_workflow and saved_workflow['fingerprint'] == fingerprint:
            result = saved_workflow['result']
            st.divider()
            st.subheader('1. Planner Agent')
            st.write(result.get('plan',''))
            st.subheader('2. Gemini Coder Agent')
            st.code(result.get('fixed_code',''),language='python')
            st.subheader('3. Reviewer Agent')
            decision = result.get('review','UNKNOWN')
            details = result.get('review_details','')
            if decision == 'REJECTED':
                st.error(decision)
            elif decision == 'SYNTAX VALID':
                st.info('SYNTAX VALID — Tests not executed')
            else:
                st.warning(decision)
            st.write(details)
            st.subheader('4. Code Comparison')
            left,right = st.columns(2)
            with left:
                st.markdown('**Original Code**')
                st.code(code,language='python')
            with right:
                st.markdown('**Proposed Code**')
                st.code(result.get('fixed_code',''),language='python')
            st.subheader('Code Differences')
            st.code(result.get('diff') or 'No changes.',language='diff')
            st.download_button('⬇️ Download Proposed Fix',data=result.get('fixed_code',''),
                               file_name='fixed_' + Path(selected_file).name,mime='text/x-python')

elif page == 'Code Comparison':
    st.header('Code Comparison')
    uploaded = st.session_state.uploaded_project
    saved = st.session_state.uploaded_workflow_result
    if selected_project == UPLOAD_OPTION and uploaded:
        files = uploaded['files']
        filename = st.selectbox('Select File',sorted(files.keys()),key='comparison_file')
        original = files[filename]
        fingerprint = file_fingerprint(filename,original)
        fixed = saved['result'].get('fixed_code','') if saved and saved['fingerprint'] == fingerprint else ''
    else:
        st.caption('Showing the local bug_demo comparison.')
        data = st.session_state.result
        filename = 'calculator.py'
        original = data['original'] if data else read_source()
        fixed = data['fixed'] if data else ''
    left,right = st.columns(2)
    with left:
        st.subheader('Original')
        st.code(original,language='python')
    with right:
        st.subheader('Proposed Fix')
        if fixed:
            st.code(fixed,language='python')
        else:
            st.info('Run the corresponding agent workflow first.')
    if fixed:
        st.subheader('Differences')
        st.code(make_diff(original,fixed,filename) or 'No changes.',language='diff')
        st.download_button('Download Proposed Fix',data=fixed,
                           file_name='fixed_' + Path(filename).name,mime='text/x-python')

elif page == 'Agent Workflow':
    st.header('Agent Workflow')
    st.subheader('Trusted Local Demo: Seven Stages')
    stages = [
        ('0. pgvector Semantic Retrieval','Retrieve indexed code relevant to the issue'),
        ('1. Code Search MCP','Read project files'),
        ('2. Git MCP','Check repository status'),
        ('3. Test Runner MCP','Run original local tests'),
        ('4. Gemini Planner','Analyze bug and plan the fix'),
        ('5. Gemini Coder','Generate proposed corrected code'),
        ('6. Reviewer','Test proposed code in a temporary copy'),
    ]
    for name,description in stages:
        with st.container(border=True):
            st.subheader(name)
            st.write(description)
    st.divider()
    st.subheader('Uploaded File: Three Stages')
    for name,description in [('1. Planner','Analyze potential bugs'),
                             ('2. Coder','Generate a proposed fix'),
                             ('3. Reviewer','Validate Python syntax')]:
        with st.container(border=True):
            st.subheader(name)
            st.write(description)
    st.info('Uploaded-project tests and MCP execution are not connected. '
            'A temporary directory alone is not a secure sandbox for untrusted code.')

elif page == 'Execution Logs':
    st.header('Execution Logs')
    data = st.session_state.result
    if data:
        st.caption(f"Last local run: {data['timestamp']}")
        st.subheader('Local Standard Output')
        st.code(data['stdout'],language='text')
        if data['stderr']:
            with st.expander('Error Logs'):
                st.code(data['stderr'],language='text')
        st.download_button('Download Local Logs',data=data['stdout']+'\n\n'+data['stderr'],
                           file_name='devpilot_logs.txt',mime='text/plain')
    else:
        st.info('No local execution logs yet.')
    saved = st.session_state.uploaded_workflow_result
    if saved:
        st.divider()
        st.subheader('Latest Uploaded Agent Result')
        result = saved['result']
        st.json({'review':result.get('review'),
                 'review_details':result.get('review_details'),'tests_executed':False})

st.divider()
st.caption('DevPilot AI | Gemini + LangGraph + MCP + pgvector + GitHub + Streamlit')
