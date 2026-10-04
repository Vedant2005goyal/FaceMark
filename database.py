from contextlib import contextmanager

from mysql.connector import pooling

from config import Config


class DatabaseManager:
    """Singleton wrapper around one MySQL connection pool shared by the whole process.

    Every query borrows a connection and returns it right away, so the API's
    threads never share a connection and nobody pays to open a new one per query.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._pool = pooling.MySQLConnectionPool(
                pool_name="attendance_pool",
                pool_size=5,
                pool_reset_session=True,
                host=Config.DB_HOST,
                port=Config.DB_PORT,
                user=Config.DB_USER,
                password=Config.DB_PASSWORD,
                database=Config.DB_NAME,
            )
        return cls._instance

    @contextmanager
    def transaction(self):
        """Yield a cursor (rows come back as dicts). Everything inside the block commits
        together, or rolls back if an exception is raised."""
        conn = self._pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()  # returns the connection to the pool

    def execute_query(self, query, params=None, fetch=False, fetch_one=False):
        """Run one statement. Returns a row (fetch_one), all rows (fetch), or the new row's id."""
        with self.transaction() as cursor:
            cursor.execute(query, params or ())
            if fetch_one:
                return cursor.fetchone()
            if fetch:
                return cursor.fetchall()
            return cursor.lastrowid
