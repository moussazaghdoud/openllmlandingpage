FROM nats:2.10-alpine

COPY nats-leaf.conf /etc/nats/nats-leaf.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh

RUN chmod +x /docker-entrypoint.sh

EXPOSE 4222

ENTRYPOINT ["/docker-entrypoint.sh"]
