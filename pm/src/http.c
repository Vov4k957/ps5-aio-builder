#include "http.h"
#include <arpa/inet.h>
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <netinet/in.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define MAX_REPLY (16u*1024*1024)
long long clock_ms(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (long long)t.tv_sec*1000+t.tv_nsec/1000000;}
void pause_ms(int ms){struct timespec t={ms/1000,(ms%1000)*1000000L};while(nanosleep(&t,&t)&&errno==EINTR){}}
static int wait_fd(int fd,short events,long long deadline){
    for(;;){long long left=deadline-clock_ms();if(left<=0){errno=ETIMEDOUT;return -1;}
        struct pollfd p={fd,events,0};int n=poll(&p,1,left>INT_MAX?INT_MAX:(int)left);
        if(n>0){if(p.revents&events)return 0;if((events&POLLIN)&&(p.revents&POLLHUP))return 0;return -1;}
        if(n<0&&errno==EINTR)continue;
        return -1;
    }
}
int url_encode(const char *s,char *out,size_t cap){
    static const char hex[]="0123456789ABCDEF";size_t n=0;
    for(;*s;s++){unsigned char c=(unsigned char)*s;int plain=isalnum(c)||strchr("-._~",c);
        if(n+(plain?1u:3u)>=cap)return -1;
        if(plain)out[n++]=(char)c;else{out[n++]='%';out[n++]=hex[c>>4];out[n++]=hex[c&15];}}
    if(n>=cap)return -1;
    out[n]=0;return 0;
}
void http_free(Http *r){free(r->body);*r=(Http){0};}
int http_call(int port,const char *method,const char *path,const char *body,int timeout_ms,Http *out){
    *out=(Http){0};int fd=-1,rc=-1;char *buf=NULL;size_t used=0,cap=8192,header=0,expected=0;
    int have_length=0;long long deadline=clock_ms()+timeout_ms;
    if(strpbrk(path,"\r\n ")||strlen(path)>8192)return -1;
    char request[16384];size_t body_len=body?strlen(body):0;
    int n=snprintf(request,sizeof(request),"%s %s HTTP/1.0\r\nHost: 127.0.0.1:%d\r\nConnection: close\r\nX-PLDMGR-Request: 1\r\nContent-Type: application/json\r\nContent-Length: %zu\r\n\r\n%s",method,path,port,body_len,body?body:"");
    if(n<0||(size_t)n>=sizeof(request))return -1;
    fd=socket(AF_INET,SOCK_STREAM,0);if(fd<0)return -1;
    int flags=fcntl(fd,F_GETFL,0);if(flags<0||fcntl(fd,F_SETFL,flags|O_NONBLOCK))goto done;
    struct sockaddr_in addr={0};addr.sin_family=AF_INET;addr.sin_port=htons((unsigned short)port);addr.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    if(connect(fd,(struct sockaddr*)&addr,sizeof(addr))<0){
        if(errno!=EINPROGRESS)goto done;
        if(wait_fd(fd,POLLOUT,deadline))goto done;
        int error=0;socklen_t size=sizeof(error);if(getsockopt(fd,SOL_SOCKET,SO_ERROR,&error,&size)||error)goto done;
    }
    for(size_t off=0;off<(size_t)n;){
        if(wait_fd(fd,POLLOUT,deadline))goto done;
        ssize_t w=send(fd,request+off,(size_t)n-off,0);
        if(w>0){off+=(size_t)w;out->sent=1;}
        else if(w<0&&(errno==EINTR||errno==EAGAIN||errno==EWOULDBLOCK))continue;else goto done;
    }
    buf=malloc(cap+1);if(!buf)goto done;
    for(;;){
        if(header&&have_length&&used-header==expected)break;
        if(used==cap){if(cap>=MAX_REPLY)goto done;cap*=2;if(cap>MAX_REPLY)cap=MAX_REPLY;char *p=realloc(buf,cap+1);if(!p)goto done;buf=p;}
        if(wait_fd(fd,POLLIN,deadline))goto done;
        ssize_t got=recv(fd,buf+used,cap-used,0);
        if(got==0)break;
        if(got<0){if(errno==EINTR||errno==EAGAIN||errno==EWOULDBLOCK)continue;goto done;}
        if(memchr(buf+used,0,(size_t)got))goto done;
        used+=(size_t)got;buf[used]=0;
        if(!header){
            char *end=strstr(buf,"\r\n\r\n");
            if(!end){if(used>16384)goto done;continue;}
            header=(size_t)(end-buf)+4;
            if(header>16384||sscanf(buf,"HTTP/%*d.%*d %d",&out->status)!=1)goto done;
            char *p=strstr(buf,"\r\n");if(!p)goto done;p+=2;
            while(p<end){char *e=strstr(p,"\r\n");if(!e||e>end)goto done;
                if(!strncasecmp(p,"Transfer-Encoding:",18))goto done; /* HTTP/1.0: no chunked framing. */
                if(!strncasecmp(p,"Content-Length:",15)){
                    if(have_length)goto done;
                    char *q=p+15;while(q<e&&(*q==' '||*q=='\t'))q++;
                    if(q==e)goto done;
                    size_t v=0;for(;q<e;q++){if(*q<'0'||*q>'9'||v>MAX_REPLY/10)goto done;v=v*10+(size_t)(*q-'0');}
                    if(v>MAX_REPLY-header)goto done;
                    expected=v;have_length=1;
                }
                p=e+2;
            }
        }
        if(header&&have_length&&used-header>expected)goto done;
    }
    if(!header||(have_length&&used-header!=expected))goto done;
    out->body=malloc(used-header+1);if(!out->body)goto done;
    memcpy(out->body,buf+header,used-header);out->body[used-header]=0;rc=0;
done:
    free(buf);if(fd>=0)close(fd);return rc;
}
