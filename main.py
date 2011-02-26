#!/usr/bin/env python
# -*- coding: utf-8 -*-
from google.appengine.ext import webapp
from google.appengine.dist import use_library
use_library('django', '1.2')
from google.appengine.ext.webapp import util, template
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.api import memcache
import urllib, datetime, re, os
step = 10

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
    try:
      page = int(pageStr)
    except ValueError:
      page = 0
    entries = Entry.all().order("-datetime")
    if not users.is_current_user_admin():
      entries = entries.filter("datetime <", datetime.datetime.now())
      entries = entries.filter("public =", True)
    entries = entries.fetch(step + 1, page * step)
    params = {
      'entries': entries[:step],
      'login': users.is_current_user_admin(),
      'logout_url': users.create_logout_url("/"),
    }
    if len(entries) > step:
      params['next'] = page + 1
    if page > 0:
      params['prev'] = page - 1 
    print_with_template(self, 'index.html', params)

class RSSHandler(AuthHandler):
  def get(self, pageStr):
    print_with_template(self, 'rss.xml', {'entries':Entry.all().order("-datetime").filter("datetime <", datetime.datetime.now()).filter("public =", True).fetch(30)})

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
  def get(self, key):
    tagStr = urllib.unquote(key).decode('utf-8')
    tag = Tag.all().filter("tag =", tagStr).get()
    if tag:
      entries = tag.entries
      entries = entries.filter("datetime <", datetime.datetime.now())
      entries = entries.filter("public =", True)
      params = {
        'entries': entries[:step],
        'login': users.is_current_user_admin(),
        'logout_url': users.create_logout_url("/"),
      }
      print_with_template(self, 'index.html', params)
    else:
      print_with_template(self, 'error.html', {'message':"Tag %s does not exist" % h(tagStr)})

class EntryHandler(AuthHandler):
  def get(self, key):
    print_with_template(self, 'index.html', {'entries':[Entry.get(key)], 'detail':True})

class UploaderHandler(AuthHandler):
  def get2(self):
    print_with_template(self, 'upload.html', {'images':Image.all()})
  def post2(self):
    if self.request.get('file'):
      image = Image()
      image.image = self.request.POST.get('file').file.read()
      image.contentType = self.request.body_file.vars['file'].headers['content-type']
      image.put()
    self.redirect('/uploader')

class DeleteImageHandler(AuthHandler):
  def get2(self, key):
    Image.get(key).delete()
    self.redirect('/uploader')

class ImageHandler(AuthHandler):
  def get(self, key):
    image = quickGet(key)
    self.response.headers['Content-Type'] = image.contentType.encode('utf-8')
    self.response.out.write(image.image)

def quickGet(key):
  data = memcache.get(key)
  if data == None:
    data = db.get(key)
    memcache.set(key = key, value = data, time=3600)
  return data

def urlReplacer(match, limit = 45):
  return '<a href="%s" target="_blank">%s</a>' % (match.group(), match.group()[:limit] + ('...' if len(match.group()) > limit else ''))

def linkURLs(str):
  return re.sub(r'([^"]|^)(https?|ftp)(://[\w:;/.?%#&=+-]+)', urlReplacer, str)

def replaceImages(str):
  return re.sub(r'\[img:(.*)\]', r'<img src="/image/\1" style="max-width:400px">', str)

def replaceStrongs(str):
  str = re.sub(r'\[strong\]', r'<strong>', str)
  str = re.sub(r'\[/strong\]', r'</strong>', str)
  return str

def nl2br(str):
  return str.replace('\r\n','\n').replace('\n','<br />\n')

def print_with_template(self, view, params = {}):
  fpath = os.path.join(os.path.dirname(__file__), 'templates', view)
  html = template.render(fpath, params)
  self.response.out.write(html)

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
    return replaceImages(replaceStrongs(linkURLs(nl2br(h(self.body)))))
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
  image = db.BlobProperty()
  contentType = db.StringProperty()

def main():
  application = webapp.WSGIApplication([
    ('/tag/(.*)', TagHandler),
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

def h(html):
  return html.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')

if __name__ == '__main__':
  main()