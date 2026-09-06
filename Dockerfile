FROM python:3.11-slim

WORKDIR /app

# 先复制源码和 README，再由 setuptools 安装当前项目。
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["evoquant", "--host", "0.0.0.0", "--port", "8000"]
