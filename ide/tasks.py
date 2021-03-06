from celery import task

from ide.models import Project, SourceFile, ResourceFile, ResourceIdentifier, BuildResult
from ide.git import git_auth_check, get_github
from django.utils import simplejson as json
from django.utils.timezone import now
from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.db import transaction
from django.contrib.auth.models import User


import tempfile
import os
import os.path
import subprocess
import shutil
import zipfile
import uuid
import urllib2
import re
import hashlib
from github import Github, BadCredentialsException, GithubException
from github.InputGitTreeElement import InputGitTreeElement
from github.GithubObject import NotSet
import base64
import traceback


def create_sdk_symlinks(project_root, sdk_root):
    SDK_LINKS = ["waf", "wscript", "tools", "lib", "pebble_app.ld", "include"]

    for item_name in SDK_LINKS:
        os.symlink(os.path.join(sdk_root, item_name), os.path.join(project_root, item_name))

    os.symlink(os.path.join(sdk_root, os.path.join("resources", "wscript")),
               os.path.join(project_root, os.path.join("resources", "wscript")))

def link_or_copy(src, dst):
    try:
        os.link(src, dst)
    except OSError as e:
        if e.errno == 18:
            shutil.copy(src, dst)
        else:
            raise

@task(ignore_result=True, acks_late=True)
def run_compile(build_result, optimisation=None):
    build_result = BuildResult.objects.get(pk=build_result)
    project = build_result.project
    source_files = SourceFile.objects.filter(project=project)
    resources = ResourceFile.objects.filter(project=project)
    if optimisation is None:
        optimisation = project.optimisation

    # Assemble the project somewhere
    base_dir = tempfile.mkdtemp(dir=os.path.join(settings.CHROOT_ROOT, 'tmp') if settings.CHROOT_ROOT else None)
    print "Compiling in %s" % base_dir

    try:
        os.makedirs(build_result.get_dir())
    except OSError:
        pass

    try:
        # Create symbolic links to the original files
        # Source code
        src_dir = os.path.join(base_dir, 'src')
        os.mkdir(src_dir)
        for f in source_files:
            abs_target = os.path.abspath(os.path.join(src_dir, f.file_name))
            if not abs_target.startswith(src_dir):
                raise Exception("Suspicious filename: %s" % f.file_name)
            abs_target_dir = os.path.dirname(abs_target)
            if not os.path.exists(abs_target_dir):
                print "Creating directory %s." % abs_target_dir
                os.makedirs(abs_target_dir)
            link_or_copy(os.path.abspath(f.local_filename), abs_target)

        # Resources
        resource_root = 'resources/src' if project.sdk_version == '1' else 'resources'
        os.makedirs(os.path.join(base_dir, resource_root, 'images'))
        os.makedirs(os.path.join(base_dir, resource_root, 'fonts'))
        os.makedirs(os.path.join(base_dir, resource_root, 'data'))

        if project.sdk_version == '1':
            print "Writing out resource map"
            resource_dict = generate_resource_dict(project, resources)
            open(os.path.join(base_dir, resource_root, 'resource_map.json'), 'w').write(json.dumps(resource_dict))
        else:
            print "Writing out manifest"
            manifest_dict = generate_v2_manifest_dict(project, resources)
            open(os.path.join(base_dir, 'appinfo.json'), 'w').write(json.dumps(manifest_dict))

        for f in resources:
            target_dir = os.path.abspath(os.path.join(base_dir, resource_root, ResourceFile.DIR_MAP[f.kind]))
            abs_target = os.path.abspath(os.path.join(target_dir, f.file_name))
            if not abs_target.startswith(target_dir):
                raise Exception("Suspicious filename: %s" % f.file_name)
            print "Added %s %s" % (f.kind, f.local_filename)
            link_or_copy(os.path.abspath(f.local_filename), abs_target)


        # Reconstitute the SDK
        if project.sdk_version == '1':
            print "Symlinking SDK"
            create_sdk_symlinks(base_dir, os.path.abspath(settings.SDK1_ROOT))
        elif project.sdk_version == '2':
            print "Inserting wscript"
            open(os.path.join(base_dir, 'wscript'), 'w').write(generate_wscript_file(project))
            print "Inserting jshintrc"
            open(os.path.join(base_dir, 'pebble-jshintrc'), 'w').write(generate_jshint_file(project))

        # Build the thing
        print "Beginning compile"
        cwd = os.getcwd()
        success = False
        output = 'Failed to get output'
        try:
            if settings.CHROOT_JAIL is not None:
                output = subprocess.check_output([settings.CHROOT_JAIL, project.sdk_version, base_dir[len(settings.CHROOT_ROOT):], optimisation], stderr=subprocess.STDOUT)
            else:
                os.chdir(base_dir)
                if project.sdk_version == '1':
                    print "Running SDK1 build"
                    output = subprocess.check_output(["./waf", "configure"], stderr=subprocess.STDOUT)
                    output += subprocess.check_output(["./waf", "build"], stderr=subprocess.STDOUT)
                elif project.sdk_version == '2':
                    print "Running SDK2 build"
                    output = subprocess.check_output(["pebble", "build"], stderr=subprocess.STDOUT)
                    print "output", output
        except subprocess.CalledProcessError as e:
            output = e.output
            success = False
        else:
            success = True
            temp_file = os.path.join(base_dir, 'build', '%s.pbw' % os.path.basename(base_dir))
            if not os.path.exists(temp_file):
                success = False
                print "Success was a lie."
        finally:
            os.chdir(cwd)

            if success:
                # Try reading file sizes out of it first.
                try:
                    s = os.stat(temp_file)
                    build_result.total_size = s.st_size
                    # Now peek into the zip to see the component parts
                    with zipfile.ZipFile(temp_file, 'r') as z:
                        build_result.binary_size = z.getinfo('pebble-app.bin').file_size
                        build_result.resource_size = z.getinfo('app_resources.pbpack').file_size
                except Exception as e:
                    print "Couldn't extract filesizes: %s" % e

                shutil.move(temp_file, build_result.pbw)
                print "Build succeeded."
            else:
                print "Build failed."
            open(build_result.build_log, 'w').write(output)
            build_result.state = BuildResult.STATE_SUCCEEDED if success else BuildResult.STATE_FAILED
            build_result.finished = now()
            build_result.save()
    except Exception as e:
        print "Build failed due to internal error: %s" % e
        traceback.print_exc()
        build_result.state = BuildResult.STATE_FAILED
        build_result.finished = now()
        try:
            open(build_result.build_log, 'w').write("Something broke:\n%s" % e)
        except:
            pass
        build_result.save()
    finally:
        print "Removing temporary directory"
        shutil.rmtree(base_dir)


def generate_resource_dict(project, resources):
    resource_map = {'media': []}
    if project.sdk_version == '1':
        resource_map['friendlyVersion'] = 'VERSION'
        resource_map['versionDefName'] = project.version_def_name

    if project.sdk_version == '1' and len(resources) == 0:
        print "No resources; adding dummy."
        resource_map['media'].append({"type": "raw", "defName": "DUMMY", "file": "resource_map.json"})
    else:
        for resource in resources:
            for resource_id in resource.get_identifiers():
                d = {
                    'type': resource.kind,
                    'file': resource.path
                }
                if project.sdk_version == '1':
                    d['defName'] = resource_id.resource_id
                else:
                    d['name'] = resource_id.resource_id
                if resource_id.character_regex:
                    d['characterRegex'] = resource_id.character_regex
                if resource_id.tracking:
                    d['trackingAdjust'] = resource_id.tracking
                if resource.is_menu_icon:
                    d['menuIcon'] = True
                resource_map['media'].append(d)
    return resource_map


def dict_to_pretty_json(d):
    return json.dumps(d, indent=4, separators=(',', ': ')) + "\n"


def generate_resource_map(project, resources):
    return dict_to_pretty_json(generate_resource_dict(project, resources))

def generate_v2_manifest_dict(project, resources):
    manifest = {
        'uuid': str(project.app_uuid),
        'shortName': project.app_short_name,
        'longName': project.app_long_name,
        'companyName': project.app_company_name,
        'versionCode': project.app_version_code,
        'versionLabel': project.app_version_label,
        'watchapp': {
            'watchface': project.app_is_watchface
        },
        'appKeys': json.loads(project.app_keys),
        'resources': generate_resource_dict(project, resources),
        'capabilities': project.app_capabilities.split(',')
    }
    return manifest

def generate_v2_manifest(project, resources):
    return dict_to_pretty_json(generate_v2_manifest_dict(project, resources))

def generate_jshint_file(project):
    return """
/*
 * Example jshint configuration file for Pebble development.
 *
 * Check out the full documentation at http://www.jshint.com/docs/options/
 */
{
  // Declares the existence of the globals available in PebbleKit JS.
  "globals": {
    "Pebble": true,
    "console": true,
    "XMLHttpRequest": true,
    "navigator": true, // For navigator.geolocation
    "localStorage": true,
    "setTimeout": true
  },

  // Do not mess with standard JavaScript objects (Array, Date, etc)
  "freeze": true,

  // Do not use eval! Keep this warning turned on (ie: false)
  "evil": false,

  /*
   * The options below are more style/developer dependent.
   * Customize to your liking.
   */

  // All variables should be in camelcase - too specific for CloudPebble builds to fail
  // "camelcase": true,

  // Do not allow blocks without { } - too specific for CloudPebble builds to fail.
  // "curly": true,

  // Prohibits the use of immediate function invocations without wrapping them in parentheses
  "immed": true,

  // Don't enforce indentation, because it's not worth failing builds over
  // (especially given our somewhat lacklustre support for it)
  "indent": false,

  // Do not use a variable before it's defined
  "latedef": "nofunc",

  // Spot undefined variables
  "undef": "true",

  // Spot unused variables
  "unused": "true"
}
"""

def generate_wscript_file(project):
    jshint = project.app_jshint
    wscript = """
#
# This file is the default set of rules to compile a Pebble project.
#
# Feel free to customize this to your needs.
#

from sh import jshint, ErrorReturnCode_2
hint = jshint

top = '.'
out = 'build'

def options(ctx):
    ctx.load('pebble_sdk')

def configure(ctx):
    ctx.load('pebble_sdk')
    global hint
    hint = hint.bake(['--config', 'pebble-jshintrc'])

def build(ctx):
    if {{jshint}}:
        try:
            hint("src/js/pebble-js-app.js", _tty_out=False) # no tty because there are none in the cloudpebble sandbox.
        except ErrorReturnCode_2 as e:
            ctx.fatal("\\nJavaScript linting failed (you can disable this in Project Settings):\\n" + e.stdout)

    ctx.load('pebble_sdk')

    ctx.pbl_program(source=ctx.path.ant_glob('src/**/*.c'),
                    target='pebble-app.elf')

    ctx.pbl_bundle(elf='pebble-app.elf',
                   js=ctx.path.ant_glob('src/js/**/*.js'))

"""
    return wscript.replace('{{jshint}}', 'True' if jshint else 'False')

def add_project_to_archive(z, project, prefix=''):
    source_files = SourceFile.objects.filter(project=project)
    resources = ResourceFile.objects.filter(project=project)
    prefix = prefix + re.sub(r'[^\w]+', '_', project.name).strip('_').lower()

    for source in source_files:
        z.writestr('%s/src/%s' % (prefix, source.file_name), source.get_contents())

    for resource in resources:
        res_path = 'resources/src' if project.sdk_version == '1' else 'resources'
        z.writestr('%s/%s/%s' % (prefix, res_path, resource.path), open(resource.local_filename).read())

    if project.sdk_version == '1':
        resource_map = generate_resource_map(project, resources)
        z.writestr('%s/resources/src/resource_map.json' % prefix, resource_map)
    else:
        manifest = generate_v2_manifest(project, resources)
        z.writestr('%s/appinfo.json' % prefix, manifest)
        # This file is always the same, but needed to build.
        z.writestr('%s/wscript' % prefix, generate_wscript_file(project))


@task(acks_late=True)
def create_archive(project_id):
    project = Project.objects.get(pk=project_id)
    prefix = re.sub(r'[^\w]+', '_', project.name).strip('_').lower()
    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp:
        filename = temp.name
        with zipfile.ZipFile(filename, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            add_project_to_archive(z, project)

        # Generate a URL
        u = uuid.uuid4().hex
        outfile = '%s%s/%s.zip' % (settings.EXPORT_DIRECTORY, u, prefix)
        os.makedirs(os.path.dirname(outfile), 0755)
        shutil.copy(filename, outfile)
        os.chmod(outfile, 0644)
        return '%s%s/%s.zip' % (settings.EXPORT_ROOT, u, prefix)

@task(acks_late=True)
def export_user_projects(user_id):
    user = User.objects.get(pk=user_id)
    projects = Project.objects.filter(owner=user)
    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp:
        filename = temp.name
        with zipfile.ZipFile(filename, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            for project in projects:
                add_project_to_archive(z, project, prefix='cloudpebble-export/')

        # Generate a URL
        u = uuid.uuid4().hex
        outfile = '%s%s/%s.zip' % (settings.EXPORT_DIRECTORY, u, 'cloudpebble-export')
        os.makedirs(os.path.dirname(outfile), 0755)
        shutil.copy(filename, outfile)
        os.chmod(outfile, 0644)
        return '%s%s/%s.zip' % (settings.EXPORT_ROOT, u, 'cloudpebble-export')

class NoProjectFoundError(Exception):
    pass


def find_project_root(contents):
    RESOURCE_MAP = 'resources/src/resource_map.json'
    MANIFEST = 'appinfo.json'
    SRC_DIR = 'src/'
    version = None
    for base_dir in contents:
        version = None
        print base_dir
        # Try finding v2
        try:
            dir_end = base_dir.index(MANIFEST)
            print dir_end
        except ValueError:
            # Try finding v1
            try:
                dir_end = base_dir.index(RESOURCE_MAP)
            except ValueError:
                continue
            else:
                if dir_end + len(RESOURCE_MAP) != len(base_dir):
                    continue
                version = '1'
        else:
            if dir_end + len(MANIFEST) != len(base_dir):
                print 'failed'
                continue
            version = '2'

        base_dir = base_dir[:dir_end]
        print base_dir
        for source_dir in contents:
            if source_dir[:dir_end] != base_dir:
                continue
            if source_dir[-2:] != '.c':
                continue
            if source_dir[dir_end:dir_end+len(SRC_DIR)] != SRC_DIR:
                continue
            break
        else:
            continue
        break
    else:
        raise Exception("No project root found.")
    return (version, base_dir)


@task(acks_late=True)
def do_import_archive(project_id, archive_location, delete_zip=False, delete_project=False):
    try:
        project = Project.objects.get(pk=project_id)
        # archive_location *must not* be a file-like object. We ensure this by string casting.
        archive_location = str(archive_location)
        if not zipfile.is_zipfile(archive_location):
            raise NoProjectFoundError("The file is not a zip file.")

        with zipfile.ZipFile(str(archive_location), 'r') as z:
            contents = z.infolist()
            # Requirements:
            # - Find the folder containing the project. This may or may not be at the root level.
            # - Read in the source files, resources and resource map.
            # Observations:
            # - Legal projects must keep their source in a directory called 'src' containing at least one *.c file.
            # - Legal projects must have a resource map at resources/src/resource_map.json
            # Strategy:
            # - Find the shortest common prefix for 'resources/src/resource_map.json' and 'src/'.
            #   - This is taken to be the project directory.
            # - Import every file in 'src/' with the extension .c or .h as a source file
            # - Parse resource_map.json and import files it references
            RESOURCE_MAP = 'resources/src/resource_map.json'
            MANIFEST = 'appinfo.json'
            SRC_DIR = 'src/'
            if len(contents) > 200:
                raise Exception("Too many files in zip file.")
            file_list = [x.filename for x in contents]

            version, base_dir = find_project_root(file_list)
            dir_end = len(base_dir)
            project.sdk_version = version

            # Now iterate over the things we found
            with transaction.commit_on_success():
                for entry in contents:
                    filename = entry.filename
                    if filename[:dir_end] != base_dir:
                        continue
                    filename = filename[dir_end:]
                    if filename == '':
                        continue
                    if not os.path.normpath('/SENTINEL_DO_NOT_ACTUALLY_USE_THIS_NAME/%s' % filename).startswith('/SENTINEL_DO_NOT_ACTUALLY_USE_THIS_NAME/'):
                        raise SuspiciousOperation("Invalid zip file contents.")
                    if entry.file_size > 5242880:  # 5 MB
                        raise Exception("Excessively large compressed file.")

                    if (filename == RESOURCE_MAP and version == '1') or (filename == MANIFEST and version == '2'):
                        # We have a resource map! We can now try importing things from it.
                        with z.open(entry) as f:
                            m = json.loads(f.read())

                        if version == '1':
                            project.version_def_name = m['versionDefName']
                            media_map = m['media']
                        elif version == '2':
                            project.app_uuid = m['uuid']
                            project.app_short_name = m['shortName']
                            project.app_long_name = m['longName']
                            project.app_company_name = m['companyName']
                            project.app_version_code = m['versionCode']
                            project.app_version_label = m['versionLabel']
                            project.app_is_watchface = m.get('watchapp', {}).get('watchface', False)
                            project.app_capabilities = ','.join(m.get('capabilities', []))
                            project.app_keys = dict_to_pretty_json(m.get('appKeys', {}))
                            media_map = m['resources']['media']

                        resources = {}
                        for resource in media_map:
                            kind = resource['type']
                            def_name = resource['defName'] if version == '1' else resource['name']
                            file_name = resource['file']
                            regex = resource.get('characterRegex', None)
                            tracking = resource.get('trackingAdjust', None)
                            is_menu_icon = resource.get('menuIcon', False)
                            if file_name not in resources:
                                resources[file_name] = ResourceFile.objects.create(project=project, file_name=os.path.basename(file_name), kind=kind, is_menu_icon=is_menu_icon)
                                local_filename = resources[file_name].get_local_filename(create=True)
                                res_path = 'resources/src' if version == '1' else 'resources'
                                open(local_filename, 'w').write(z.open('%s%s/%s' % (base_dir, res_path, file_name)).read())
                            ResourceIdentifier.objects.create(
                                resource_file=resources[file_name],
                                resource_id=def_name,
                                character_regex=regex,
                                tracking=tracking
                            )

                    elif filename.startswith(SRC_DIR):
                        if (not filename.startswith('.')) and (filename.endswith('.c') or filename.endswith('.h') or filename.endswith('js/pebble-js-app.js')):
                            base_filename = os.path.basename(filename) if not filename.endswith('.js') else 'js/pebble-js-app.js'
                            source = SourceFile.objects.create(project=project, file_name=base_filename)
                            with z.open(entry.filename) as f:
                                source.save_file(f.read().decode('utf-8'))
                project.save()

        # At this point we're supposed to have successfully created the project.
        if delete_zip:
            try:
                os.unlink(archive_location)
            except OSError:
                print "Unable to remove archive at %s." % archive_location
        return True
    except:
        if delete_project:
            try:
                Project.objects.get(pk=project_id).delete()
            except:
                pass
        raise


@task(acks_late=True)
def do_import_github(project_id, github_user, github_project, github_branch, delete_project=False):
    try:
        url = "https://github.com/%s/%s/archive/%s.zip" % (github_user, github_project, github_branch)
        if file_exists(url):
            u = urllib2.urlopen(url)
            with tempfile.NamedTemporaryFile(suffix='.zip') as temp:
                shutil.copyfileobj(u, temp)
                temp.flush()
                return do_import_archive(project_id, temp.name)
        else:
            raise Exception("The branch '%s' does not exist." % github_branch)
    except:
        if delete_project:
            try:
                Project.objects.get(pk=project_id).delete()
            except:
                pass
        raise

def file_exists(url):
    request = urllib2.Request(url)
    request.get_method = lambda : 'HEAD'
    try:
        response = urllib2.urlopen(request)
        return True
    except:
        return False


def git_sha(content):
    return hashlib.sha1('blob %d\x00%s' % (len(content), content)).hexdigest()


def git_blob(repo, sha):
    return base64.b64decode(repo.get_git_blob(sha).content)


# SDK2 support has made this function a huge, unmaintainable mess.
@git_auth_check
def github_push(user, commit_message, repo_name, project):
    g = Github(user.github.token, client_id=settings.GITHUB_CLIENT_ID, client_secret=settings.GITHUB_CLIENT_SECRET)
    repo = g.get_repo(repo_name)
    try:
        branch = repo.get_branch(project.github_branch or repo.master_branch)
    except GithubException:
        raise Exception("Unable to get branch.")
    commit = repo.get_git_commit(branch.commit.sha)
    tree = repo.get_git_tree(commit.tree.sha, recursive=True)

    paths = [x.path for x in tree.tree]

    next_tree = {x.path: InputGitTreeElement(path=x.path, mode=x.mode, type=x.type, sha=x.sha) for x in tree.tree}

    try:
        remote_version, root = find_project_root(paths)
    except:
        remote_version, root = project.sdk_version, ''

    src_root = root + 'src/'
    project_sources = project.source_files.all()
    has_changed = False
    for source in project_sources:
        repo_path = src_root + source.file_name
        if repo_path not in next_tree:
            has_changed = True
            next_tree[repo_path] = InputGitTreeElement(path=repo_path, mode='100644', type='blob', content=source.get_contents())
            print "New file: %s" % repo_path
        else:
            sha = next_tree[repo_path]._InputGitTreeElement__sha
            our_content = source.get_contents()
            expected_sha = git_sha(our_content)
            if expected_sha != sha:
                print "Updated file: %s" % repo_path
                next_tree[repo_path]._InputGitTreeElement__sha = NotSet
                next_tree[repo_path]._InputGitTreeElement__content = our_content
                has_changed = True

    expected_source_files = [src_root + x.file_name for x in project_sources]
    for path in next_tree.keys():
        if not path.startswith(src_root):
            continue
        if path not in expected_source_files:
            del next_tree[path]
            print "Deleted file: %s" % path
            has_changed = True

    # Now try handling resource files.

    resources = project.resources.all()

    old_resource_root = root + ("resources/src/" if remote_version == '1' else 'resources/')
    new_resource_root = root + ("resources/src/" if project.sdk_version == '1' else 'resources/')

    # Migrate all the resources so we can subsequently ignore the issue.
    if old_resource_root != new_resource_root:
        print "moving resources"
        new_next_tree = next_tree.copy()
        for path in next_tree:
            if path.startswith(old_resource_root) and not path.endswith('resource_map.json'):
                new_path = new_resource_root + path[len(old_resource_root):]
                print "moving %s to %s" % (path, new_path)
                next_tree[path]._InputGitTreeElement__path = new_path
                new_next_tree[new_path] = next_tree[path]
                del new_next_tree[path]
        next_tree = new_next_tree

    for res in resources:
        repo_path = new_resource_root + res.path
        if repo_path in next_tree:
            content = res.get_contents()
            if git_sha(content) != next_tree[repo_path]._InputGitTreeElement__sha:
                print "Changed resource: %s" % repo_path
                has_changed = True
                blob = repo.create_git_blob(base64.b64encode(content), 'base64')
                print "Created blob %s" % blob.sha
                next_tree[repo_path]._InputGitTreeElement__sha = blob.sha
        else:
            print "New resource: %s" % repo_path
            blob = repo.create_git_blob(base64.b64encode(res.get_contents()), 'base64')
            print "Created blob %s" % blob.sha
            next_tree[repo_path] = InputGitTreeElement(path=repo_path, mode='100644', type='blob', sha=blob.sha)

    # Both of these are used regardless of version
    remote_map_path = root + 'resources/src/resource_map.json'
    remote_manifest_path = root + 'appinfo.json'

    if remote_version == '1':
        remote_map_sha = next_tree[remote_map_path]._InputGitTreeElement__sha if remote_map_path in next_tree else None
        if remote_map_sha is not None:
            their_res_dict = json.loads(git_blob(repo, remote_map_sha))
        else:
            their_res_dict = {'friendlyVersion': 'VERSION', 'versionDefName': '', 'media': []}
        their_manifest_dict = {}
    elif remote_version == '2':
        remote_manifest_sha = next_tree[remote_manifest_path]._InputGitTreeElement__sha if remote_map_path in next_tree else None
        if remote_manifest_sha is not None:
            their_manifest_dict = json.loads(git_blob(repo, remote_manifest_sha))
            their_res_dict = their_manifest_dict['resources']
        else:
            their_manifest_dict = {}
            their_res_dict = {'media': []}


    if project.sdk_version == '1':
        our_res_dict = generate_resource_dict(project, resources)
    elif project.sdk_version == '2':
        our_manifest_dict = generate_v2_manifest_dict(project, resources)
        our_res_dict = our_manifest_dict['resources']

    if our_res_dict != their_res_dict:
        print "Resources mismatch."
        has_changed = True
        # Try removing things that we've deleted, if any
        to_remove = set(x['file'] for x in their_res_dict['media']) - set(x['file'] for x in our_res_dict['media'])
        for path in to_remove:
            repo_path = new_resource_root + path
            if repo_path in next_tree:
                print "Deleted resource: %s" % repo_path
                del next_tree[repo_path]

        # Update the stored resource map, if applicable.
        if project.sdk_version == '1':
            if remote_map_path in next_tree:
                next_tree[remote_map_path]._InputGitTreeElement__sha = NotSet
                next_tree[remote_map_path]._InputGitTreeElement__content = dict_to_pretty_json(our_res_dict)
            else:
                next_tree[remote_map_path] = InputGitTreeElement(path=remote_map_path, mode='100644', type='blob', content=dict_to_pretty_json(our_res_dict))
            # Delete the v2 manifest, if one exists
            if remote_manifest_path in next_tree:
                del next_tree[remote_manifest_path]
    # This one is separate because there's more than just the resource map changing.
    if (project.sdk_version == '2' and their_manifest_dict != our_manifest_dict):
        if remote_manifest_path in next_tree:
            next_tree[remote_manifest_path]._InputGitTreeElement__sha = NotSet
            next_tree[remote_manifest_path]._InputGitTreeElement__content = generate_v2_manifest(project, resources)
        else:
            next_tree[remote_manifest_path] = InputGitTreeElement(path=remote_manifest_path, mode='100644', type='blob', content=generate_v2_manifest(project, resources))
        # Delete the v1 manifest, if one exists
        if remote_map_path in next_tree:
            del next_tree[remote_map_path]


    # Commit the new tree.
    if has_changed:
        print "Has changed; committing"
        # GitHub seems to choke if we pass the raw directory nodes off to it,
        # so we delete those.
        for x in next_tree.keys():
            if next_tree[x]._InputGitTreeElement__mode == '040000':
                del next_tree[x]
                print "removing subtree node %s" % x

        print [x._InputGitTreeElement__mode for x in next_tree.values()]
        git_tree = repo.create_git_tree(next_tree.values())
        print "Created tree %s" % git_tree.sha
        git_commit = repo.create_git_commit(commit_message, git_tree, [commit])
        print "Created commit %s" % git_commit.sha
        git_ref = repo.get_git_ref('heads/%s' % (project.github_branch or repo.master_branch))
        git_ref.edit(git_commit.sha)
        print "Updated ref %s" % git_ref.ref
        project.github_last_commit = git_commit.sha
        project.github_last_sync = now()
        project.save()
        return True

    return False


@git_auth_check
def github_pull(user, project):
    g = get_github(user)
    repo_name = project.github_repo
    if repo_name is None:
        raise Exception("No GitHub repo defined.")
    repo = g.get_repo(repo_name)
    # If somehow we don't have a branch set, this will use the "master_branch"
    branch_name = project.github_branch or repo.master_branch
    try:
        branch = repo.get_branch(branch_name)
    except GithubException:
        raise Exception("Unable to get the branch.")

    if project.github_last_commit == branch.commit.sha:
        # Nothing to do.
        return False

    commit = repo.get_git_commit(branch.commit.sha)
    tree = repo.get_git_tree(commit.tree.sha, recursive=True)

    paths = {x.path: x for x in tree.tree}

    version, root = find_project_root(paths)

    # First try finding the resource map so we don't fail out part-done later.
    # TODO: transaction support for file contents would be nice...
    # SDK2
    resource_root = None
    media = {}
    if version == '2':
        resource_root = root + 'resources/'
        manifest_path = root + 'appinfo.json'
        if manifest_path in paths:
            manifest_sha = paths[manifest_path].sha
            manifest = json.loads(git_blob(repo, manifest_sha))
            media = manifest.get('resources', {}).get('media', [])
        else:
            raise Exception("appinfo.json not found")
    else:
        # SDK1
        resource_root = root + 'resources/src/'
        remote_map_path = resource_root + 'resource_map.json'
        if remote_map_path in paths:
            remote_map_sha = paths[remote_map_path].sha
            remote_map = json.loads(git_blob(repo, remote_map_sha))
            media = remote_map['media']
        else:
            raise Exception("resource_map.json not found.")

    for resource in media:
        path = resource_root + resource['file']
        if path not in paths:
            raise Exception("Resource %s not found in repo." % path)

    # Now we grab the zip.
    zip_url = repo.get_archive_link('zipball', branch_name)
    u = urllib2.urlopen(zip_url)
    with tempfile.NamedTemporaryFile(suffix='.zip') as temp:
        shutil.copyfileobj(u, temp)
        temp.flush()
        # And wipe the project!
        project.source_files.all().delete()
        project.resources.all().delete()
        import_result = do_import_archive(project.id, temp.name)
        project.github_last_commit = branch.commit.sha
        project.github_last_sync = now()
        project.save()
        return import_result


@task
def do_github_push(project_id, commit_message):
    project = Project.objects.select_related('owner__github').get(pk=project_id)
    return github_push(project.owner, commit_message, project.github_repo, project)


@task
def do_github_pull(project_id):
    project = Project.objects.select_related('owner__github').get(pk=project_id)
    return github_pull(project.owner, project)


@task
def hooked_commit(project_id, target_commit):
    project = Project.objects.select_related('owner__github').get(pk=project_id)
    did_something = False
    print "Comparing %s versus %s" % (project.github_last_commit, target_commit)
    if project.github_last_commit != target_commit:
        github_pull(project.owner, project)
        did_something = True

    if project.github_hook_build:
        build = BuildResult.objects.create(project=project)
        run_compile(build.id)
        did_something = True

    return did_something
