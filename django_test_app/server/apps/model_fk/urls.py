from dmr.routing import Router, path
from server.apps.model_fk import views

router = Router(
    'model-fk/',
    [
        path(
            'user/',
            views.UserController.as_view(),
            name='user',
        ),
        path(
            'user/cursor/',
            views.UserCursorController.as_view(),
            name='user-cursor',
        ),
    ],
)
