# Docker compose examples

## WordPress example

This example can be found in `compose/wordpress/`

The example is to raise up the wordpress service using environment variables to setup the DB access and it uses `xdebug` also, it's in order to debug the wordpress project.

The service in the docker compose file are:

* db: MySql server, it uses mysql version 5.7 and has a persistent volume in `db-data` folder.
* phpmyadmin: PHP my admin service, it is for access to the DB it was configured in `8090` port
* wordpress: It is the project itself, it is built from the `wordpress:php7.3-apache` version, it just has the `wp-config.php` file in order to setup that configuration.

## Instructions

1. In order to raise up the project we must configure the .env file with the needed environment variables, the `dev.env` file is the example for that.

2. Run docker-compose:

```bash
docker-compose up
```

3. Check if 3 of the services are running:

```bash
docker ps
```
