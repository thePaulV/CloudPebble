from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils.timezone import now
from django.conf import settings

import os
import os.path
import shutil
import uuid


def generate_half_uuid():
    _uuid = str(uuid.uuid4())
    if int(_uuid.split('-')[0], 16) > (0xffffffff/2):
        # Only take uuids from the bottom half of the uuid space
        bytes = 0xffffffff - int(_uuid[0:8], 16)
        _uuid = ''.join(["%08x" % bytes, _uuid[8:]])
    return _uuid

class Project(models.Model):
    owner = models.ForeignKey(User)
    name = models.CharField(max_length=50)
    last_modified = models.DateTimeField(auto_now_add=True)
    version_def_name = models.CharField(max_length=50, default="APP_RESOURCES")
    SDK_VERSIONS = (
        ('1', '1.1.2'),
        ('2', '2.0')
    )
    sdk_version = models.CharField(max_length=10, choices=SDK_VERSIONS, default='1')


    # New settings for 2.0
    app_uuid = models.CharField(max_length=36, blank=True, null=True, default=generate_half_uuid)
    app_company_name = models.CharField(max_length=100, blank=True, null=True)
    app_short_name = models.CharField(max_length=100, blank=True, null=True)
    app_long_name = models.CharField(max_length=100, blank=True, null=True)
    app_version_code = models.IntegerField(blank=True, null=True, default=1)
    app_version_label = models.CharField(max_length=40, blank=True, null=True, default='1.0')
    app_is_watchface = models.BooleanField(default=False)
    app_capabilities = models.CharField(max_length=255, blank=True, null=True)
    app_keys = models.TextField(default="{}")
    app_jshint = models.BooleanField(default=True)

    app_capability_list = property(lambda: app_capabilities.split(','))

    OPTIMISATION_CHOICES = (
        ('0', 'None'),
        ('1', 'Limited'),
        ('s', 'Prefer smaller'),
        ('2', 'Prefer faster'),
        ('3', 'Aggressive (faster, bigger)'),
    )

    optimisation = models.CharField(max_length=1, choices=OPTIMISATION_CHOICES, default='s')

    github_repo = models.CharField(max_length=100, blank=True, null=True)
    github_branch = models.CharField(max_length=100, blank=True, null=True)
    github_last_sync = models.DateTimeField(blank=True, null=True)
    github_last_commit = models.CharField(max_length=40, blank=True, null=True)
    github_hook_uuid = models.CharField(max_length=36, blank=True, null=True)
    github_hook_build = models.BooleanField(default=False)

    def get_last_build(self):
        try:
            return self.builds.order_by('-id')[0]
        except IndexError:
            return None

    def get_menu_icon(self):
        try:
            return self.resources.filter(is_menu_icon=True)[0]
        except IndexError:
            return None

    last_build = property(get_last_build)
    menu_icon = property(get_menu_icon)

    def __unicode__(self):
        return u"%s" % self.name

    class Meta:
        unique_together = (('owner', 'name'),)


class UserSettings(models.Model):
    user = models.OneToOneField(User, primary_key=True)

    AUTOCOMPLETE_ALWAYS = 1
    AUTOCOMPLETE_EXPLICIT = 2
    AUTOCOMPLETE_NEVER = 3
    AUTOCOMPLETE_CHOICES = (
        (AUTOCOMPLETE_ALWAYS, 'As-you-type'),
        (AUTOCOMPLETE_EXPLICIT, 'When pressing Ctrl-Space'),
        (AUTOCOMPLETE_NEVER, 'Never')
    )

    KEYBIND_STANDARD = 'default'
    KEYBIND_VIM = 'vim'
    KEYBIND_EMACS = 'emacs'
    KEYBIND_CHOICES = (
        (KEYBIND_STANDARD, 'Standard'),
        (KEYBIND_VIM, 'vim-like'),
        (KEYBIND_EMACS, 'emacs-like')
    )

    THEME_CHOICES = (
        ('monokai', 'Monokai (Sublime Text)'),
        ('blackboard', 'Blackboard (TextMate)'),
        ('eclipse', 'Eclipse'),
        ('solarized light', 'Solarized (light)'),
        ('solarized dark', 'Solarized (dark)'),
    )

    def __unicode__(self):
        return self.user.name

    autocomplete = models.IntegerField(choices=AUTOCOMPLETE_CHOICES, default=AUTOCOMPLETE_ALWAYS)
    keybinds = models.CharField(max_length=20, choices=KEYBIND_CHOICES, default=KEYBIND_STANDARD)
    theme = models.CharField(max_length=50, choices=THEME_CHOICES, default='monokai')

    # Used for the Pebble ownership transition, when it was set to False.
    accepted_terms = models.BooleanField(default=True)

User.settings = property(lambda self: UserSettings.objects.get_or_create(user=self)[0])

class UserGithub(models.Model):
    user = models.OneToOneField(User, primary_key=True, related_name='github')
    token = models.CharField(max_length=50, null=True, blank=True)
    nonce = models.CharField(max_length=36, null=True, blank=True)
    username = models.CharField(max_length=50, null=True, blank=True)
    avatar = models.CharField(max_length=255, null=True, blank=True)

class TemplateProject(Project):
    KIND_TEMPLATE = 1
    KIND_SDK_DEMO = 2
    KIND_EXAMPLE = 3
    KIND_CHOICES = (
        (KIND_TEMPLATE, 'Template'),
        (KIND_SDK_DEMO, 'SDK Demo'),
        (KIND_EXAMPLE, 'Example')
    )

    template_kind = models.IntegerField(choices=KIND_CHOICES, db_index=True)

    def copy_into_project(self, project):
        uuid_string = ", ".join(["0x%02X" % ord(b) for b in uuid.uuid4().bytes])
        for resource in self.resources.all():
            new_resource = ResourceFile.objects.create(project=project, file_name=resource.file_name, kind=resource.kind)
            shutil.copy(resource.local_filename, new_resource.get_local_filename(create=True))
            for i in resource.identifiers.all():
                ResourceIdentifier.objects.create(resource_file=new_resource, resource_id=i.resource_id, character_regex=i.character_regex)

        for source_file in self.source_files.all():
            new_file = SourceFile.objects.create(project=project, file_name=source_file.file_name)
            new_file.save_file(source_file.get_contents().replace("__UUID_GOES_HERE__", uuid_string))


class BuildResult(models.Model):
    STATE_WAITING = 1
    STATE_FAILED = 2
    STATE_SUCCEEDED = 3
    STATE_CHOICES = (
        (STATE_WAITING, 'Pending'),
        (STATE_FAILED, 'Failed'),
        (STATE_SUCCEEDED, 'Succeeded')
    )

    project = models.ForeignKey(Project, related_name='builds')
    uuid = models.CharField(max_length=36, default=lambda:str(uuid.uuid4()))
    state = models.IntegerField(choices=STATE_CHOICES, default=STATE_WAITING)
    started = models.DateTimeField(auto_now_add=True, db_index=True)
    finished = models.DateTimeField(blank=True, null=True)

    total_size = models.IntegerField(blank=True, null=True)
    binary_size = models.IntegerField(blank=True, null=True)
    resource_size = models.IntegerField(blank=True, null=True)

    def get_dir(self):
        return '%s%s/%s/%s/' % (settings.MEDIA_ROOT, self.uuid[0], self.uuid[1], self.uuid)

    def get_url(self):
        return '%s%s/%s/%s/' % (settings.MEDIA_URL, self.uuid[0], self.uuid[1], self.uuid)

    def get_pbw_filename(self):
        return '%swatchface.pbw' % self.get_dir()

    def get_build_log(self):
        return '%sbuild_log.txt' % self.get_dir()

    def get_pbw_url(self):
        return '%swatchface.pbw' % self.get_url()

    def get_build_log_url(self):
        return '%sbuild_log.txt' % self.get_url()

    pbw = property(get_pbw_filename)
    build_log = property(get_build_log)

    pbw_url = property(get_pbw_url)
    build_log_url = property(get_build_log_url)


class ResourceFile(models.Model):
    project = models.ForeignKey(Project, related_name='resources')
    RESOURCE_KINDS = (
        ('raw', 'Binary blob'),
        ('png', '1-bit PNG'),
        ('png-trans', '1-bit PNG with transparency'),
        ('font', 'True-Type Font')
    )

    file_name = models.CharField(max_length=100)
    kind = models.CharField(max_length=9, choices=RESOURCE_KINDS)
    is_menu_icon = models.BooleanField(default=False)

    def get_local_filename(self, create=False):
        padded_id = '%05d' % self.id
        filename = '%sresources/%s/%s/%s' % (settings.FILE_STORAGE, padded_id[0], padded_id[1], padded_id)
        if create:
            if not os.path.exists(os.path.dirname(filename)):
                os.makedirs(os.path.dirname(filename))
        return filename

    local_filename = property(get_local_filename)

    def save_file(self, stream):
        if not os.path.exists(os.path.dirname(self.local_filename)):
            os.makedirs(os.path.dirname(self.local_filename))
        out = open(self.local_filename, 'wb')
        for chunk in stream.chunks():
            out.write(chunk)
        out.close()

        self.project.last_modified = now()
        self.project.save()

    def get_contents(self):
        return open(self.local_filename).read()

    def get_identifiers(self):
        return ResourceIdentifier.objects.filter(resource_file=self)

    def save(self, *args, **kwargs):
        self.project.last_modified = now()
        self.project.save()
        super(ResourceFile, self).save(*args, **kwargs)

    DIR_MAP = {
        'png': 'images',
        'png-trans': 'images',
        'font': 'fonts',
        'raw': 'data'
    }

    def get_path(self):
        return '%s/%s' % (self.DIR_MAP[self.kind], self.file_name)

    path = property(get_path)

    class Meta:
        unique_together = (('project', 'file_name'),)


class ResourceIdentifier(models.Model):
    resource_file = models.ForeignKey(ResourceFile, related_name='identifiers')
    resource_id = models.CharField(max_length=100)
    character_regex = models.CharField(max_length=100, blank=True, null=True)
    tracking = models.IntegerField(blank=True, null=True)

    def save(self, *args, **kwargs):
        self.resource_file.project.last_modified = now()
        self.resource_file.project.save()
        super(ResourceIdentifier, self).save(*args, **kwargs)

    class Meta:
        unique_together = (('resource_file', 'resource_id'),)


class SourceFile(models.Model):
    project = models.ForeignKey(Project, related_name='source_files')
    file_name = models.CharField(max_length=100)

    def get_local_filename(self):
        padded_id = '%05d' % self.id
        return '%ssources/%s/%s/%s' % (settings.FILE_STORAGE, padded_id[0], padded_id[1], padded_id)

    def get_contents(self):
        try:
            return open(self.local_filename).read()
        except IOError:
            return ''

    def save_file(self, content):
        if not os.path.exists(os.path.dirname(self.local_filename)):
            os.makedirs(os.path.dirname(self.local_filename))
        open(self.local_filename, 'w').write(content.encode('utf-8'))

        self.project.last_modified = now()
        self.project.save()

    def save(self, *args, **kwargs):
        self.project.last_modified = now()
        self.project.save()
        super(SourceFile, self).save(*args, **kwargs)

    local_filename = property(get_local_filename)

    class Meta:
        unique_together = (('project', 'file_name'))


@receiver(post_delete)
def delete_file(sender, instance, **kwargs):
    if sender == SourceFile or sender == ResourceFile:
        try:
            os.unlink(instance.local_filename)
        except OSError:
            pass
