FROM nats:2.10-alpine

RUN mkdir -p /etc/nats /nats-config

COPY nats-leaf.conf /nats-config/nats-leaf.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh

RUN chmod +x /docker-entrypoint.sh

EXPOSE 4222

ENTRYPOINT ["/docker-entrypoint.sh"]
