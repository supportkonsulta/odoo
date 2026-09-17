FROM odoo:19.0

USER root
RUN mkdir -p /mnt/extra-addons
COPY ./custom_addons /mnt/extra-addons
RUN chmod -R 777 /mnt/extra-addons && chown -R odoo:odoo /mnt/extra-addons
USER odoo
