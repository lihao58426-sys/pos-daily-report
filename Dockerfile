# ============================================
# POS 日报推送 — Docker 打包说明书
# ============================================
# 跟项目5的 Dockerfile 最大的区别：
#   需要 Chromium（Playwright 模拟浏览器）
#   Chromium 在 Linux 里需要一堆系统库
#   playwright install-deps 自动帮我们装这些

# 第1步：选地基
# 不用 slim 版了——Chromium 需要很多系统库，slim 缺的太多
# 用完整版 Python 3.14，虽然大了点但装 Chromium 省事
FROM docker.m.daocloud.io/library/python:3.14-slim

# 第2步：设工作目录
WORKDIR /app

# 第3步：容器内全部走国内镜像（Docker 代理只管外面，管不到容器里）
RUN sed -i 's/deb.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list.d/debian.sources

# 第4步：装 Playwright + Chromium
#   pip 走阿里云镜像（避免 pip 官网被墙）
#   playwright install-deps → apt 走中科大源
#   playwright install chromium → 走 npmmirror 镜像
ENV PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/

RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ \
        playwright requests pyyaml fastapi uvicorn \
    && playwright install-deps chromium \
    && playwright install chromium \
    && rm -rf /var/lib/apt/lists/*

# 第5步：复制代码
COPY *.py .
COPY config.yaml .

# 第5步：启动命令
# 容器跑起来直接 python main.py
CMD ["python", "main.py"]

