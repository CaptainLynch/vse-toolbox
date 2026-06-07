# CODING RULES

> **硬性规则。不解释原因，不讨论例外。违反则代码不可用。**

---

## Python 后端

### R-01 文件路径安全

所有文件路径必须经过 `safe_path` 函数检查，禁止路径遍历。

```python
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent  # VSE_TOOLBOX/
DATA_DIR = BASE_DIR / "data"
TEMP_DIR = BASE_DIR / "temp"
LOGS_DIR = BASE_DIR / "logs"
OUTPUT_DIR = BASE_DIR / "templates" / "output"
DRIVERS_DIR = BASE_DIR / "drivers"

ALLOWED_DIRS = [TEMP_DIR, OUTPUT_DIR, DATA_DIR, LOGS_DIR, DRIVERS_DIR]

def safe_path(user_input: str, base_dir: Path) -> Path:
    resolved = (base_dir / user_input).resolve()
    if not any(str(resolved).startswith(str(d.resolve())) for d in ALLOWED_DIRS):
        raise ValueError(f"非法路径: {user_input}")
    return resolved
```

**违规示例**（禁止）：
```python
open(f"./temp/{user_input}", "w")          # 用户输入 ../../../etc/passwd 则崩溃
open(Path("./temp") / request.query.path)  # 未检查路径遍历
```

### R-02 SQL 参数化

所有 SQL 必须参数化。禁止字符串拼接 SQL。

**合规**：
```python
cursor.execute("SELECT * FROM issues WHERE id = ?", (issue_id,))
```

**违规**（禁止）：
```python
cursor.execute(f"SELECT * FROM issues WHERE id = '{issue_id}'")  # SQL注入
```

### R-03 文件句柄管理

所有文件操作使用 `with` 语句。禁止裸 open 不 close。

**合规**：
```python
with open(path, "w") as f:
    f.write(data)
# 自动close
```

**违规**（禁止）：
```python
f = open(path, "w")
f.write(data)
# 未close，文件句柄泄漏
```

### R-04 WebDriver 生命周期

WebDriver 实例必须在 `atexit` 注册 `quit()`。禁止创建后不关闭。

```python
import atexit

class DriverManager:
    def __init__(self):
        self._chrome = None
        self._edge = None
        atexit.register(self.quit_all)
    
    def quit_all(self):
        for d in [self._chrome, self._edge]:
            if d:
                try:
                    d.quit()
                except Exception:
                    pass
```

### R-05 数据库连接上下文

数据库连接使用上下文管理器，确保关闭。

```python
from contextlib import contextmanager
import sqlite3

@contextmanager
def get_db():
    conn = sqlite3.connect(str(DATA_DIR / "VSE_TOOLBOX.db"))
    try:
        yield conn
    finally:
        conn.close()

# 使用
with get_db() as conn:
    cursor = conn.cursor()
    cursor.execute("...")
```

### R-06 临时文件清理

temp/ 目录内容在程序启动时自动清理（保留最近24小时的文件）。

```python
import tempfile
import shutil
from datetime import datetime, timedelta

def cleanup_temp():
    cutoff = datetime.now() - timedelta(hours=24)
    for f in TEMP_DIR.iterdir():
        if f.is_file() and datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
            f.unlink()
        elif f.is_dir():
            shutil.rmtree(f, ignore_errors=True)
```

### R-07 敏感信息不打印

邮件内容、问题描述等敏感信息不写入日志。

**合规**：
```python
logger.info(f"处理邮件 {mail_id} 成功")          # 只记录ID
# 不记录: logger.info(f"邮件内容: {mail.content}")  # 违规
```

### R-08 硬编码禁止

密码、Token、密钥通过环境变量或配置文件读取。禁止硬编码。

**合规**：
```python
import os
secret = os.environ.get("FEISHU_SECRET", "")
```

**违规**（禁止）：
```python
SECRET = "abc123"  # 硬编码
```

### R-09 WebDriver 自带

WebDriver 必须从 `./drivers/` 加载。禁止从 PATH 或系统目录加载。

**合规**：
```python
from selenium.webdriver.chrome.service import Service as ChromeService
svc = ChromeService(str(DRIVERS_DIR / "chromedriver.exe"))
```

**违规**（禁止）：
```python
driver = webdriver.Chrome()  # 从PATH加载，依赖系统环境
```

### R-10 不可写系统目录

禁止写入以下目录：
- `C:/Windows/`
- `C:/Program Files/`
- `C:/ProgramData/`
- 注册表（`winreg` 模块禁止使用）
- 系统环境变量 PATH

允许写入：
- `./data/` `./temp/` `./logs/` `./templates/output/`
- `%USERPROFILE%/` 及其子目录

---

## TypeScript 前端

### R-11 API 错误处理

所有 API 调用必须 try-catch，错误时显示友好提示。

```typescript
async function getIssues(params?: IssueParams): Promise<PaginatedIssues> {
  try {
    const res = await fetch(`/api/issues?${new URLSearchParams(params)}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: '请求失败' }));
      throw new Error(err.message);
    }
    return (await res.json()).data;
  } catch (e) {
    console.error('获取问题列表失败:', e);
    // fallback: 返回mock数据或空数组
    return { items: [], total: 0, page: 1, size: 20 };
  }
}
```

### R-12 文件上传不手动设 Content-Type

multipart 上传让浏览器自动设置 Content-Type。

**合规**：
```typescript
const formData = new FormData();
files.forEach(f => formData.append('files', f));
fetch('/api/excel/merge', { method: 'POST', body: formData });  // 不设headers
```

**违规**（禁止）：
```typescript
fetch('/api/excel/merge', {
  headers: { 'Content-Type': 'multipart/form-data' },  // 错误！浏览器会自动设置boundary
  body: formData
});
```

### R-13 HashRouter 强制使用

必须使用 HashRouter，不能用 BrowserRouter。

```typescript
// main.tsx
import { HashRouter } from 'react-router-dom';

<HashRouter>
  <App />
</HashRouter>
```

### R-14 离线检测

启动时检测后端可用性，不可用时显示提示。

```typescript
// App.tsx
useEffect(() => {
  fetch('/api/issues?page=1&size=1', { signal: AbortSignal.timeout(3000) })
    .then(() => setOnline(true))
    .catch(() => setOnline(false));
}, []);
```

---

## 通用

### R-15 Git 忽略

```gitignore
# 不提交
__pycache__/
*.pyc
*.pyo
.env
data/VSE_TOOLBOX.db
logs/
temp/
templates/output/*.pptx
templates/output/*.png
dist/          # 前端build产物由CI生成
```

### R-16 日志级别

| 级别 | 用途 |
|------|------|
| DEBUG | 开发调试，生产关闭 |
| INFO | 关键操作记录（功能调用、成功完成） |
| WARNING | 可恢复异常（网络超时、文件不存在） |
| ERROR | 不可恢复异常（数据库连接失败、WebDriver崩溃） |

### R-17 代码风格

- Python: PEP8, 4空格缩进, 行宽120
- TypeScript: 单引号, 2空格缩进, 行宽100, 分号可选但统一

---

最后更新：2026-05-28
