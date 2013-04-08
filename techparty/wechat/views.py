#encoding=utf-8

from django.http import HttpResponse
from django.contrib.auth.models import User
from django.views.generic.base import View
from django.conf import settings
from wechat.official import WxApplication
from wechat.official import WxTextResponse
from social_auth.models import UserSocialAuth
from techparty.wechat.models import Command
from techparty.wechat.models import UserState
from techparty.wechat.commands import interactive_cmds
import random
import pylibmc
cache = pylibmc.Client()


def log_err():
    import sys
    info = sys.exc_info()
    print 'full exception'
    print info[0]
    print info[1]
    print info[2]

class TechpartyView(View, WxApplication):

    SECRET_TOKEN = settings.TECHPARTY_OFFICIAL_TOKEN

    def get(self, request):
        if '__text__' in request.GET and '__code__' in request.GET:
            if request.GET['__code__'] != settings.DEBUG_SECRET:
                return HttpResponse(u'invalid debug code')
            xml = """<xml>
            <ToUserName><![CDATA[techparty]]></ToUserName>
            <FromUserName><![CDATA[testuser]]></FromUserName>
            <CreateTime>1348831860</CreateTime>
            <MsgType><![CDATA[text]]></MsgType>
            <Content><![CDATA[%s]]></Content>
            <MsgId>1234567890123456</MsgId>
            </xml>
            """ % request.GET['__text__']
            self.debug_mode = True
            return HttpResponse(self.process(request.GET, xml),
                                mimetype='text/xml')
        else:
            return HttpResponse(self.process(request.GET))

    def post(self, request):
        print 'begin post'
        print request.body
        return HttpResponse(self.process(request.GET, request.body))

    def get_actions(self):
        actionMap = {}
        commands = cache.get('buildin_commands')
        if not commands:
            commands = Command.objects.all()
            cache.set('buildin_commands', commands)
        for command in commands:
            actionMap[command.name] = command
            for alias in command.alias.split(','):
                actionMap[alias] = command
        actionMap.update(interactive_cmds)
        print actionMap
        return actionMap

    def is_valid_params(self, auth_params):
        if getattr(self, 'debug_mode', ''):
            return True
        else:
            return super(TechpartyView, self).is_valid_params(auth_params)

    def on_text(self, text):
        """处理用户发来的文本，
        - 先检查用户当前的状态（State）。如果用户带状态，则优先交给状态机处理
        - 用户无状态，则交由命令处理器分配处理。
        """
        print u'on text wxstate %s' % self.wxstate
        if self.wxstate:
            command = interactive_cmds[self.wxstate.command]
            return command.execute(self.wxreq, self.user,
                                       self.wxstate)
        else:
            print 'no wxstate found'
            command = self.get_actions().get(text.Content)
            print 'command %s' % command
            if not command:
                # 尝试一下模糊匹配
                blurs = [(k, v) for k, v in self.get_actions().iteritems()
                         if isinstance(v, Command) and not v.precise]
                for blur in blurs:
                    if blur[0] in text.Content:
                        command = blur[1]
                        break
                if not command:
                    return WxTextResponse(u'感谢您的反馈', text)
            if isinstance(command, Command):
                print 'return command'
                return command.as_response(text)
            else:
                print u'excute command with state %s' % self.wxstate
                return command.execute(self.wxreq, self.user,
                                       self.wxstate)

    def on_image(self):
        pass

    def on_link(self):
        pass

    def on_location(self):
        pass

    def pre_process(self):
        """在处理命令前检查用户的状态。
        - 先检查用户是否存在，不存在先保存用户。
        - 再检查用户是否已在某个状态，如有，则把用户状态保存至实例。
        """
        social = UserSocialAuth.objects.filter(provider='weixin',
                                               uid=self.wxreq.FromUserName)
        print 'social get? %s' % social
        if social:
            social = social[0]
            self.user = social.user
        else:
            try:
                user = User.objects.create_user('default_' +
                                                str(random.randint(1, 10000)))
                user.save()
                user.username = 'wx_%d' % user.id
                user.save()
                self.user = user
                social = UserSocialAuth(user=user, provider='weixin',
                                        uid=self.wxreq.FromUserName)
                social.save()
            except:
                log_err()
        print u'social user %s' % social.user
        try:
            self.wxstate = UserState.objects.get(user=social.user.username)
        except:
            log_err()
            self.wxstate = None
        print u'wxstate %s' % self.wxstate
