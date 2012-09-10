This project tries to port `JaikuEngine
<http://code.google.com/p/jaikuengine/>`_ to `Django-nonrel
<https://github.com/django-nonrel>`_, it is WIP now.

Go http://jaiku-nonrel.appspot.com to have a try.

INSTALL
=======

1. Download and install App Engine SDK for Python into ``/usr/local/``.
2. Checkout this repo, and copy ``local_settings.example.py`` to
   ``local_settings.py`` in ``jaikuengine`` to run server locally.
3. Run ``python manage.py runserver``.

DEPLOY
======

1. Modify application name in app.yaml and settings.py.
2. Run ``python manage.py deploy``.

Remember to remove ``local_settings.py``.
