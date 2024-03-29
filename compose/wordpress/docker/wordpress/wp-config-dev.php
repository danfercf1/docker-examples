<?php

if (getenv('WP_ENVIRONMENT_TYPE') === 'production') {
    // Production environment
    /** The name of the database for WordPress */
    define('DB_NAME', 'wp_production');
    
    /** MySQL database username */
    define('DB_USER', 'production_user');
    
    /** MySQL database password */
    define('DB_PASSWORD', 'production_password');
    
    /** MySQL hostname */
    define('DB_HOST', 'localhost');
    
    define('WP_DEBUG', false);
    define('WP_DEBUG_LOG', false);
} else {
    /** The name of the database for WordPress */
    define('DB_NAME', getenv('WORDPRESS_DB_NAME'));

    /** MySQL database username */
    define('DB_USER', getenv('WORDPRESS_DB_USER'));

    /** MySQL database password */
    define('DB_PASSWORD', getenv('WORDPRESS_DB_PASSWORD'));

    /** MySQL hostname */
    define('DB_HOST', getenv('WORDPRESS_DB_HOST'));

    define('WP_DEBUG', getenv('WORDPRESS_DEBUG'));
    define('WP_DEBUG_LOG', getenv('WORDPRESS_DEBUG_LOG'));
}

/** Database Charset to use in creating database tables. */
define( 'DB_CHARSET', 'utf8' );

/** The Database Collate type. Don't change this if in doubt. */
define( 'DB_COLLATE', '' );

/**#@+
 * Authentication Unique Keys and Salts.
 *
 * Change these to different unique phrases!
 * You can generate these using the {@link https://api.wordpress.org/secret-key/1.1/salt/ WordPress.org secret-key service}
 * You can change these at any point in time to invalidate all existing cookies. This will force all users to have to log in again.
 *
 * @since 2.6.0
 */
define('AUTH_KEY',         'G61<x])xwPw7WT^l?%wdZ;44|n2iklS5pYXV.Kzty~%H{ZgjdS:^}|%wb7ITheSr');
define('SECURE_AUTH_KEY',  'u#N;4yY`!nMqz:Z`D|~|/3x:[rF_*u0U;.Y]/x**(|u~R3&H|[DUSc `8a^ @,4G');
define('LOGGED_IN_KEY',    '74#:5}+OK[~`9kC26kTz+:HAS_C,V)Lj^A?)+hz;$Z~D adWD{=GAI|qNE&zrp2U');
define('NONCE_KEY',        '7V#DJ7AD55)&3 p:[P&y}(K-$*Me[dS_@ jH=+Xu:6zN.+yh&nI.L<O@pU<3 l~g');
define('AUTH_SALT',        'y5rBTbJ vxJ```/ +dHK:C-]=gSn2{P)%21i[[ykw,cz/mR_l,{.1=5TM#*#Ug-t');
define('SECURE_AUTH_SALT', ';wv,d-xvWI2lMxwn) LzugRSXc#t[?Kp4G(ox-fEsF9vGlN~4L%Z(M$,%6<Xhi+}');
define('LOGGED_IN_SALT',   'cB- {}ByNs|CSE03=Yax^ec7|wY(3<o4zNm<nZxvJ]se0f#1tjy]T-RO2f(H7l;+');
define('NONCE_SALT',       '2zXk^H,jD%C%+h$XZB.VEnS]0+XH6pU;hM&8Dr8p%^$G[>~9@KD~0@?N!$Ey=dfi');

/**#@-*/

/**
 * WordPress Database Table prefix.
 *
 * You can have multiple installations in one database if you give each
 * a unique prefix. Only numbers, letters, and underscores please!
 */
$table_prefix = 'wp_';

/* That's all, stop editing! Happy publishing. */

/** Absolute path to the WordPress directory. */
if ( ! defined( 'ABSPATH' ) ) {
	define( 'ABSPATH', __DIR__ . '/' );
}

/** Sets up WordPress vars and included files. */
require_once ABSPATH . 'wp-settings.php';
