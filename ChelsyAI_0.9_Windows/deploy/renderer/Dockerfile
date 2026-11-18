FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1
RUN pip install --no-cache-dir python-docx==1.2.0 python-pptx==1.0.2 openpyxl==3.1.5 fpdf2==2.8.4 pypdf==6.12.0
WORKDIR /opt/chelsy
COPY mind/artifacts/builder.py /opt/chelsy/mind/artifacts/builder.py
COPY assets/fonts /opt/chelsy/assets/fonts
COPY deploy/renderer/entry.py /opt/chelsy/mind/artifacts/entry.py
USER 65532:65532
ENTRYPOINT ["python","/opt/chelsy/mind/artifacts/entry.py"]
