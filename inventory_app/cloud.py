"""Cloud Run entry point: ephemeral compute, external data, no background daemon."""
import os

from waitress import serve

from app import create_app


def main():
    app = create_app({'CLOUD_MODE': True})
    serve(app, host='0.0.0.0', port=int(os.environ.get('PORT', '8080')), threads=4,
          max_request_body_size=12*1024*1024, channel_timeout=60,
          # Only for direct run.app ingress: the nearest proxy appends the client IP.
          # Adding another load balancer requires re-validating this hop count.
          trusted_proxy='*', trusted_proxy_count=1,
          trusted_proxy_headers={'x-forwarded-for'},
          url_scheme='https', clear_untrusted_proxy_headers=True)


if __name__ == '__main__':
    main()
