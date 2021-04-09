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
define( 'AUTH_KEY',         'put your unique phrase here' );
define( 'SECURE_AUTH_KEY',  'put your unique phrase here' );
define( 'LOGGED_IN_KEY',    'put your unique phrase here' );
define( 'NONCE_KEY',        'put your unique phrase here' );
define( 'AUTH_SALT',        'put your unique phrase here' );
define( 'SECURE_AUTH_SALT', 'put your unique phrase here' );
define( 'LOGGED_IN_SALT',   'put your unique phrase here' );
define( 'NONCE_SALT',       'put your unique phrase here' );

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
