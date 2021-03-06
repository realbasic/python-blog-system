#!/usr/bin/env python
# -*- coding: utf-8 -*-
from google.appengine.ext import webapp, db
from google.appengine.dist import use_library
use_library('django', '1.2')
from google.appengine.ext.webapp import util, template
from google.appengine.api import users, memcache
import urllib, datetime, re, os
from ConfigParser import ConfigParser
config = os.path.join(os.path.dirname(__file__), "config")
default = {"step" : "10",
           "analytics" : "UA-XXXXXXXX-X"}
parser = ConfigParser(default)
f_in = open(config, "r")
parser.readfp(f_in)
f_in.close()
step = parser.getint("default","step")
google_analytics = parser.get("log", "google_analytics")

class AuthHandler(webapp.RequestHandler):
  def get(self, key = ""):
    if users.get_current_user() == None:
      self.response.out.write("<a href=\"%s\">Sign in or register</a>." % users.create_login_url("/admin"))
    elif users.is_current_user_admin() != True:
      self.response.out.write('Your account %s is not admin. <a href=\"%s\">Log out</a> and log in with an admin account.' % (users.get_current_user(), users.create_logout_url("/admin")))
    else:
      if key:
        self.get2(key)
      else:
        self.get2()
  def post(self, key = ""):
    if users.is_current_user_admin():
      if key:
        self.post2(key)
      else:
        self.post2()

class MainHandler(AuthHandler):
  def get(self, pageStr):
    page = parseInt(pageStr)
    entries = filter_entries(Entry.all().order("-datetime")).fetch(step + 1, page * step)
    params = {'entries': entries[:step]}
    if len(entries) > step:
      params['next'] = page + 1
    if page > 0:
      params['prev'] = page - 1 
    print_with_template(self, 'index.html', params)

class RSSHandler(AuthHandler):
  def get(self, pageStr):
    print_with_template(self, 'rss.xml', {'entries':filter_entries(Entry.all().order("-datetime")).fetch(30)})

class AdminHandler(AuthHandler):
  def get2(self):
    self.redirect("/")

class PostHandler(AuthHandler):
  def get2(self,key = ""):
    entry = Entry.get(key) if key != '' else Entry()
    print_with_template(self, 'form.html',{'entry':entry, 'key':key})
  def post2(self, key = ""):
    if self.request.get("title") != '' and self.request.get("body") != '':
      entry = Entry.get(key) if key != '' else Entry()
      entry.title = self.request.get("title")
      entry.body = self.request.get("body")
      entry.datetime = datetime.datetime.strptime(self.request.get("datetime"), "%Y-%m-%d %H:%M:%S") - datetime.timedelta(hours=9)
      entry.public = self.request.get("public") == "1"
      entry.tags = []
      for tagStr in self.request.get('tags').replace(u'　',' ').replace('  ',' ').replace(',',' ').split(' '):
        tag = Tag.all().filter("tag =", tagStr).get()
        if tag == None:
          tag = Tag(tag = tagStr)
          tag.put()
        entry.tags.append(tag.key())
      entry.put()
    self.redirect('/')

class PostCommentHandler(AuthHandler):
  def post(self, key):
    if self.request.get("comment") != '':
      Comment(
        entry = Entry.get(key), 
        comment = self.request.get("comment"),
        delpass = self.request.get("delpass"),
        nickname = self.request.get("nickname")
      ).put()
    self.redirect("/entry/%s" % key)

class DeleteHandler(AuthHandler):
  def get2(self, key):
    db.delete(Entry.get(key))
    self.redirect('/')

class DeleteCommentHandler(AuthHandler):
  def post(self, key):
    comment = Comment.get(key)
    entry_key = comment.entry.key()
    if self.request.get("delpass") == comment.delpass:
      db.delete(comment)
    self.redirect('/entry/%s' % entry_key)

class TagHandler(AuthHandler):
  def get(self, key, pageStr):
    page = parseInt(pageStr)
    tagStr = urllib.unquote(key).decode('utf-8')
    tag = Tag.all().filter("tag =", tagStr).get()
    if tag:
      entries = filter_entries(tag.entries.order("-datetime")).fetch(step + 1, page * step)
      params = {'entries': entries[:step]}
      if len(entries) > step:
        params['next'] = page + 1
      if page > 0:
        params['prev'] = page - 1 
      params['tag'] = tagStr
      print_with_template(self, 'index.html', params)
    else:
      print_with_template(self, 'error.html', {'message':"Tag %s does not exist" % h(tagStr)})

class EntryHandler(AuthHandler):
  def get(self, key):
    entry = Entry.get(key);
    if users.is_current_user_admin() or (entry.datetime > datetime.datetime.now() and entry.public):
      print_with_template(self, 'index.html', {'entries':[Entry.get(key)], 'detail':True})
    else:
      self.redirect("/")

class UploaderHandler(AuthHandler):
  def get2(self, key):
    print_with_template(self, 'upload.html', {'images': Entry.get(key).images, 'key': key})
  def post2(self, key):
    if self.request.get('file'):
      image = Image()
      image.image = self.request.POST.get('file').file.read()
      image.contentType = self.request.body_file.vars['file'].headers['content-type']
      image.entry = Entry.get(key)
      image.put()
    self.redirect('/uploader/' + key)

class DeleteImageHandler(AuthHandler):
  def get2(self, key):
    Image.get(key).delete()
    self.redirect('/uploader')

class ImageHandler(AuthHandler):
  def get(self, key):
    image = quickGet(key)
    self.response.headers['Content-Type'] = image.contentType.encode('utf-8')
    self.response.out.write(image.image)

## Functions
def quickGet(key):
  data = memcache.get(key)
  if data == None:
    data = db.get(key)
    memcache.set(key = key, value = data, time=3600)
  return data

def apply_filters(str):
  str = h(str)
  str = nl2br(str)
  str = linkURLs(str)
  str = replaceStrongs(str)
  str = replaceImages(str)
  str = replaceLists(str)
  return str

def urlReplacer(match, limit = 45):
  return '<a href="%s" target="_blank">%s</a>' % (match.group(), match.group()[:limit] + ('...' if len(match.group()) > limit else ''))

def linkURLs(str):
  return re.sub(r'([^"]|^)(https?|ftp)(://[\w:;/.?%#&=+-]+)', urlReplacer, str)

def replaceImages(str):
  return re.sub(r'\[img:(.*)\]', r'<img src="/image/\1" style="max-width:400px">', str)

def replaceStrongs(str):
  str = re.sub(r'\[s(trong)?\]', r'<strong>', str)
  str = re.sub(r'\[/s(trong)?\]', r'</strong>', str)
  return str

def replaceLists(str):
  return re.sub(re.compile('^-(.+)$', re.MULTILINE), r'<li>\1</li>', str)

def nl2br(str):
  return str.replace('\r\n','\n').replace('\n','<br />\n')

def print_with_template(self, view, params = {}):
  params.update({
    'login': users.is_current_user_admin(),
    'logout_url': users.create_logout_url("/"),
    'google_analytics': google_analytics,
  })
  fpath = os.path.join(os.path.dirname(__file__), 'templates', view)
  html = template.render(fpath, params)
  self.response.out.write(html)

def h(html):
  return html.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')

def filter_entries(entries):
  if not users.is_current_user_admin():
    entries = entries.filter("datetime <", datetime.datetime.now()).filter("public =", True)
  return entries

def parseInt(str):
  try:
    return int(str)
  except ValueError:
    return 0

## Models
class Entry(db.Model):
  title = db.StringProperty(default = "")
  body = db.TextProperty(default = "")
  tags = db.ListProperty(db.Key)
  datetime = db.DateTimeProperty(auto_now_add = True)
  public = db.BooleanProperty(default = True)
  @property
  def formattedDatetimeInJST(self):
    return (self.datetime + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
  def tagStr(self):
    return " ".join([Tag.get(x).tag for x in self.tags])
  def formatted_body(self):
    return apply_filters(self.body)
  def tagList(self):
    return [Tag.get(t).tag for t in self.tags]
  def comment_count(self):
    return self.comments.count()

class Tag(db.Model):
  tag = db.StringProperty()
  @property
  def entries(self):
    return Entry.all().filter('tags', self.key()).order('-datetime')

class Comment(db.Model):
  comment = db.TextProperty(default = "")
  entry = db.ReferenceProperty(Entry, collection_name = 'comments')
  user = db.UserProperty()
  datetime = db.DateTimeProperty(auto_now_add = True)
  delpass = db.TextProperty()
  nickname = db.TextProperty()

class Image(db.Model):
  entry = db.ReferenceProperty(Entry, collection_name = 'images')
  image = db.BlobProperty()
  contentType = db.StringProperty()

def main():
  application = webapp.WSGIApplication([
    ('/tag/(.*)/(.*)', TagHandler),
    ('/entry/(.*)', EntryHandler),
    ('/admin/?(.*)', AdminHandler),
    ('/postComment/?(.*)', PostCommentHandler),
    ('/post/?(.*)', PostHandler),
    ('/rss/?(.*)', RSSHandler),
    ('/deleteComment/?(.*)', DeleteCommentHandler),
    ('/deleteImage/(.*)', DeleteImageHandler),
    ('/delete/?(.*)', DeleteHandler),
    ('/uploader/?(.*)', UploaderHandler),
    ('/image/(.*)', ImageHandler),
    ('/(.*)', MainHandler)
  ], debug=True)
  util.run_wsgi_app(application)

if __name__ == '__main__':
  main()