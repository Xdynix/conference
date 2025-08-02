from typing import Any

from django.db import models


class Perm:
    """A descriptor for generating Django permission strings.

    When accessed from a ``models.Model`` subclass, the descriptor turns the ``action``
    (its attribute name) and the model's metadata into Django's canonical
    ``<app>.<action>_<model>`` string.

    When accessed from any other class, it simply returns the ``action`` name unchanged.

    Examples:
        >>> class MyModel(models.Model):
        ...     class Meta: # This metaclass is for doctest only.
        ...         app_label = 'app'
        ...     VIEW = Perm()
        >>> MyModel.VIEW
        'app.view_mymodel'

        >>> class MyModel2(MyModel):
        ...     class Meta: # This metaclass is for doctest only.
        ...         app_label = 'app'
        ...     UPDATE = Perm()
        >>> MyModel2.VIEW
        'app.view_mymodel2'
        >>> MyModel2.UPDATE
        'app.update_mymodel2'

        >>> class NotAModel:
        ...     FOOBAR = Perm()
        >>> NotAModel.FOOBAR
        'foobar'
    """

    def __set_name__(self, owner: Any, name: str) -> None:
        self.action = name

    def __get__(self, instance: Any, owner: type) -> str:
        if issubclass(owner, models.Model):
            meta = owner._meta
            app_label = meta.app_label
            model_name = meta.model_name
            return f"{app_label}.{self.action.lower()}_{model_name}"
        return self.action.lower()


def get_perms(cls: type) -> set[str]:
    """Return every unique permission string declared on the class.

    Examples:
        >>> class Foo(models.Model):
        ...     class Meta: # This metaclass is for doctest only.
        ...         app_label = 'app'
        ...     VIEW = Perm()
        ...     UPDATE = Perm()
        >>> sorted(get_perms(Foo))
        ['app.update_foo', 'app.view_foo']

        >>> class Bar(Foo):
        ...     class Meta: # This metaclass is for doctest only.
        ...         app_label = 'app'
        ...     CREATE = Perm()
        >>> sorted(get_perms(Bar))
        ['app.create_bar', 'app.update_bar', 'app.view_bar']
    """
    seen: set[str] = set()
    perms: set[str] = set()
    for base in cls.__mro__:
        for name, attr in base.__dict__.items():
            if name in seen:
                continue
            seen.add(name)
            if isinstance(attr, Perm):
                perms.add(getattr(cls, name))
    return perms
