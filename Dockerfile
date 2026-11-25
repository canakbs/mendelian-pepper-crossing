# Python'un resmi imajını temel al
FROM python:3.9-slim

# Çalışma dizinini ayarla
WORKDIR /app

# Bağımlılık dosyalarını kopyala ve kur
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Proje dosyalarını kopyala
COPY . .

# Uygulamanın çalışacağı portu belirt
EXPOSE 5000

# Uygulamayı başlat
# Geliştirme için Flask'in kendi sunucusunu kullanalım
# Production için gunicorn gibi bir WSGI sunucusu tercih edilmelidir.
CMD ["python", "app.py"]
