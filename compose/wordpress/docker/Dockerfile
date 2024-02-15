FROM wordpress:php8.3-apache

# Install xdebug
# RUN if [ "${http_proxy}" != "" ]; then \
#     # Needed for pecl to succeed
#     pear config-set http_proxy ${http_proxy} \
# ;fi

# RUN pecl install xdebug && docker-php-ext-enable xdebug

COPY ./wordpress/wp-config.php ../app/

RUN docker-php-ext-install mysqli pdo pdo_mysql

# Install Less for WP-CLI
RUN apt-get update && apt-get -y install less
 
# Install WP-CLI
RUN curl -s -o /usr/local/bin/wp \
    https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar \
    && chmod +x /usr/local/bin/wp