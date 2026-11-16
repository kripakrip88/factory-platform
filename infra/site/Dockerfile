# Сайт pmkpark.ru (1С-Битрикс, шаблон aspro-allcorp2): PHP 8.3 + Apache, как на 141.133.188.220 (mod_php,
# .htaccess). Расширения — те, что были там (php -m), кроме mcrypt (Битрикс 8.3 не нужен).
FROM php:8.3.35-apache
RUN set -eux; apt-get update; \
    apt-get install -y --no-install-recommends libfreetype6-dev libjpeg62-turbo-dev libpng-dev libwebp-dev \
      libzip-dev libxslt1-dev libbz2-dev libicu-dev msmtp-mta; \
    docker-php-ext-configure gd --with-freetype --with-jpeg --with-webp; \
    docker-php-ext-install -j"$(nproc)" gd mysqli pdo_mysql zip xsl bz2 calendar exif gettext sockets intl opcache; \
    a2enmod rewrite headers expires deflate remoteip; \
    rm -rf /var/lib/apt/lists/*
COPY conf/php.ini /usr/local/etc/php/conf.d/zz-pmkpark.ini
COPY conf/apache-site.conf /etc/apache2/sites-available/000-default.conf
