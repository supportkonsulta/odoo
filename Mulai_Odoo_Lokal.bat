@echo off
echo ==============================================
echo  MEMATIKAN ODOO WINDOWS SERVICE (PENYEBAB ERROR)
echo ==============================================
net stop odoo-server-19.0

echo.
echo ==============================================
echo  MENJALANKAN ODOO SERVER LOKAL
echo ==============================================
echo Server sedang berjalan... Jangan tutup jendela ini!
echo Buka browser dan refresh (F5) localhost:8069.
echo.

"C:\Program Files\Odoo 19.0.20260826\python\python.exe" "C:\Program Files\Odoo 19.0.20260826\server\odoo-bin" -c "D:\odoo_sif\odoo.conf"
pause
