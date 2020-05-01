from logging import info
from pathlib import Path

from datasets.services import get_s3_client
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from dramatiq import actor, set_broker
from dramatiq.brokers.rabbitmq import RabbitmqBroker
from tika import parser

# Esse bloco (feio) faz com que esse módulo funcione dentro ou fora do Django
try:
    from datasets.models import File
except ImproperlyConfigured:
    import configurations
    import os

    os.environ.setdefault("DJANGO_CONFIGURATION", "Dev")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
    configurations.setup()
    from datasets.models import File


rabbitmq_broker = RabbitmqBroker(url=settings.CLOUDAMQP_URL)
set_broker(rabbitmq_broker)
client = get_s3_client(settings)


@actor
def content_from_file(file_pk=None, path=None, keep_file=True):
    if not any([file_pk, path]):
        raise Exception("Ou `file_pk` ou `path` devem ser informados.")

    a_file = None
    if file_pk:
        a_file = File.objects.get(pk=file_pk)

        if a_file.content is not None:
            return a_file.content

        path = client.download_file(a_file.s3_file_path)
        keep_file = False

    if not Path(path).exists():
        info(f"Arquivo {path} não encontrado.")
        return

    raw = parser.from_file(path)

    if not keep_file:
        Path(path).unlink()

    if a_file:
        a_file.content = raw["content"]
        a_file.save()

    return raw["content"]


@actor
def backup_file(file_id):
    try:
        file_obj = File.objects.get(pk=file_id, s3_url__isnull=True)
    except File.DoesNotExist:
        info(f"O arquivo ({file_id}) não existe ou já possui backup.")
        return

    model_name = file_obj.content_object._meta.model_name
    file_path = (
        f"{model_name}/{file_obj.created_at.year}/"
        f"{file_obj.created_at.month}/{file_obj.created_at.day}/"
    )

    s3_url, s3_file_path = client.upload_file(
        file_obj.url, file_path, file_obj.checksum
    )
    file_obj.s3_file_path = s3_file_path
    file_obj.s3_url = s3_url
    file_obj.save()

    return s3_url
