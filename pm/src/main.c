/* PM AutoUpdate: native PM API coordinator, not an ELF downloader/loader.
 * Network payload installation and launch are performed exclusively by PM.
 */
#include "json.h"
#include "http.h"
#include "generated_defaults.h"
#include "third_party/sha256.h"
#include <arpa/inet.h>
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/file.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>
#ifndef PM_HOST_TEST
#include <sys/sysctl.h>
#endif

enum { NANODNS, KSTUFF, ELFLDR, FTPSRV, WEBSRV, SHADOWMOUNT, YT_BLOCKER, HUSH, DUMP_FORGE, COUNT };
extern const unsigned char pm_dns_seed[], pm_dns_seed_end[];
#define FILE_LIMIT (512LL*1024*1024)
static const char *ids[COUNT]={"nanodns","kstuff-local","elfldr","ftpsrv","websrv","shadowmountplus","yt-blocker","hush","dump-forge"};
static const char *basenames[COUNT]={"nanodns.elf","kstuff.elf","elfldr-ps5.elf","ftpsrv-ps5.elf","websrv-ps5.elf","shadowmountplus.elf","YT-Blocker_v1.0.2.elf","hush.elf",""};
typedef struct { int id,delay,enabled; } Step;
typedef struct {
    char source[1024],dns[512],kstuff[512];
    int auto_update,ready_ms,api_ms,dns_ms,refresh_ms,install_ms,budget_ms,launch_ms;
    Step steps[COUNT];
} Config;
typedef struct { char slot[128],path[512],version[64],hash[65];int own,needs_slot; } Installed;
typedef struct { char version[64],hash[65];int present; } Available;
static Config cfg;
static int port=8084,updates=0,problems=0;
static char state_dir[512]="/data/pldmgr/pm-autoupdate";
static FILE *logfile;

static void logmsg(const char *fmt,...) {
    char line[2048];va_list ap;va_start(ap,fmt);vsnprintf(line,sizeof(line),fmt,ap);va_end(ap);
    printf("[pm-auto] %s\n",line);fflush(stdout);
    if(logfile){fprintf(logfile,"%lld %s\n",clock_ms(),line);fflush(logfile);}
}
static void notify(const char *message) {
    logmsg("%s",message);
#ifndef PM_HOST_TEST
    struct { char reserved[45];char message[3075]; } req={0};
    extern int sceKernelSendNotificationRequest(int,void*,size_t,int);
    snprintf(req.message,sizeof(req.message),"PM AutoUpdate: %s",message);
    sceKernelSendNotificationRequest(0,&req,sizeof(req),0);
#endif
}
static int path_join(char *out,size_t size,const char *suffix) {
    int n=snprintf(out,size,"%s/%s",state_dir,suffix);return n<0||(size_t)n>=size?-1:0;
}
static char *read_text(const char *path,size_t limit) {
    FILE *f=fopen(path,"rb");if(!f)return NULL;
    struct stat st;
    if(fstat(fileno(f),&st)||!S_ISREG(st.st_mode)||st.st_size<0||(unsigned long long)st.st_size>limit){fclose(f);errno=EINVAL;return NULL;}
    size_t n=(size_t)st.st_size;char *s=malloc(n+1);if(!s){fclose(f);return NULL;}
    int bad=fread(s,1,n,f)!=n; if(fclose(f))bad=1;
    if(bad||memchr(s,0,n)){free(s);errno=EINVAL;return NULL;}s[n]=0;return s;
}
static int atomic_write(const char *path,const void *data,size_t len) {
    char tmp[1024];int n=snprintf(tmp,sizeof(tmp),"%s.tmp-XXXXXX",path);
    if(n<0||(size_t)n>=sizeof(tmp))return -1;
    int fd=mkstemp(tmp);if(fd<0)return -1;
    const unsigned char *bytes=data;size_t pos=0;int bad=0;
    while(pos<len){ssize_t w=write(fd,bytes+pos,len-pos);if(w>0)pos+=(size_t)w;else if(w<0&&errno==EINTR)continue;else{bad=1;break;}}
    if(fsync(fd))bad=1;
    if(close(fd))bad=1;
    if(!bad&&rename(tmp,path))bad=1;
    if(bad)unlink(tmp);
    return bad?-1:0;
}
static int atomic_text(const char *path,const char *text) {
    return atomic_write(path,text,strlen(text));
}
static int valid_elf(const char *path) {
    int fd=open(path,O_RDONLY|O_NONBLOCK|O_NOFOLLOW);if(fd<0)return 0;
    unsigned char h[20];struct stat st;
    int ok=!fstat(fd,&st)&&S_ISREG(st.st_mode)&&st.st_size>=64&&st.st_size<=FILE_LIMIT&&
        read(fd,h,sizeof(h))==(ssize_t)sizeof(h)&&!memcmp(h,"\177ELF\2\1",6)&&h[18]==62&&h[19]==0;
    close(fd);return ok;
}
/* A clean PS5 configured to use 127.0.0.1 cannot resolve GitHub yet.
 * PM can launch any validated ELF below /data/pldmgr, even before it has a repo slot. */
static int materialize_dns(Installed *dns) {
    size_t size=(uintptr_t)pm_dns_seed_end-(uintptr_t)pm_dns_seed;
    if(path_join(dns->path,sizeof(dns->path),"bootstrap-nanodns.elf") ||
       atomic_write(dns->path,pm_dns_seed,size) || !valid_elf(dns->path))return -1;
    dns->needs_slot=1;
    logmsg("No local nanoDNS. Starting the bundled Drakmor bootstrap.");
    return 0;
}
static void wait_gap(long long previous,int delay) {
    long long remaining=previous+delay-clock_ms();
    if(remaining>0)pause_ms((int)remaining);
}
static int backup_elf(int id,const char *source,char *dest,size_t cap) {
    char suffix[128];snprintf(suffix,sizeof(suffix),"fallback/%s.elf",ids[id]);
    if(path_join(dest,cap,suffix)||!valid_elf(source))return -1;
    if(!strcmp(dest,source))return 0;
    char tmp[1024];snprintf(tmp,sizeof(tmp),"%s.tmp-XXXXXX",dest);
    int in=open(source,O_RDONLY|O_NOFOLLOW),out=-1,rc=-1;
    if(in<0)return -1;
    out=mkstemp(tmp);if(out<0){close(in);return -1;}
    char buf[65536];long long total=0;
    for(;;){ssize_t n=read(in,buf,sizeof(buf));if(!n)break;if(n<0){if(errno==EINTR)continue;goto done;}
        total+=n;if(total>FILE_LIMIT)goto done;
        for(ssize_t p=0;p<n;){ssize_t w=write(out,buf+p,(size_t)(n-p));if(w>0)p+=w;else if(w<0&&errno==EINTR)continue;else goto done;}}
    if(fsync(out))goto done;
    if(close(out)){out=-1;goto done;}out=-1;
    if(!valid_elf(tmp)||rename(tmp,dest))goto done;
    rc=0;
done:
    close(in);if(out>=0)close(out);if(rc)unlink(tmp);return rc;
}
static int get_string(const Json *j,int obj,const char *key,char *out,size_t cap) {
    return json_string(j,json_get(j,obj,key),out,cap);
}
static int id_index(const char *id) {for(int i=0;i<COUNT;i++)if(!strcmp(id,ids[i]))return i;return -1;}
/* Upgrade precisely the old shipped order. Keep custom paths, opt-outs and
 * deliberately edited sequences. Do not rewrite the user's file. */
static void migrate_v1(void) {
    static const int old_delays[COUNT]={1000,1000,1000,1000,1000,3000,0,0,0};
    for(int i=0;i<COUNT;i++)
        if(cfg.steps[i].id!=i || cfg.steps[i].delay!=old_delays[i])return;
    Step yt=cfg.steps[YT_BLOCKER];
    cfg.steps[6]=cfg.steps[7];
    cfg.steps[7]=cfg.steps[8];
    cfg.steps[8]=yt;
    for(int i=0;i<COUNT;i++) cfg.steps[i].delay=i<7?1000:(i==7?3000:0);
    if(cfg.refresh_ms==10000)cfg.refresh_ms=120000;
    if(cfg.budget_ms==300000)cfg.budget_ms=900000;
}
static int parse_config(char *text) {
    Json j;if(json_parse(&j,text))return -1;
    int schema,rc=-1;
    if(json_int(&j,json_get(&j,0,"schema"),&schema)||(schema!=1&&schema!=2)||
       get_string(&j,0,"source_url",cfg.source,sizeof(cfg.source))||
       strncmp(cfg.source,"https://",8)||strpbrk(cfg.source,"\r\n \t#")||
       get_string(&j,0,"bootstrap_nanodns",cfg.dns,sizeof(cfg.dns))||
       get_string(&j,0,"local_kstuff",cfg.kstuff,sizeof(cfg.kstuff))||
       json_bool(&j,json_get(&j,0,"auto_update"),&cfg.auto_update))goto done;
    const char *names[]={"pm_ready_timeout_ms","api_timeout_ms","dns_timeout_ms","refresh_timeout_ms","install_timeout_ms","update_budget_ms","launch_timeout_ms"};
    int *values[]={&cfg.ready_ms,&cfg.api_ms,&cfg.dns_ms,&cfg.refresh_ms,&cfg.install_ms,&cfg.budget_ms,&cfg.launch_ms};
    for(size_t i=0;i<sizeof(names)/sizeof(names[0]);i++)if(json_int(&j,json_get(&j,0,names[i]),values[i])||*values[i]<50||*values[i]>900000)goto done;
    int a=json_get(&j,0,"sequence");
    if(a<0||j.t[a].type!='['||j.t[a].children!=COUNT)goto done;
    unsigned seen=0;int p=a+1;
    for(int i=0;i<COUNT;i++){
        char id[64];Step *s=&cfg.steps[i];
        if(get_string(&j,p,"id",id,sizeof(id))||(s->id=id_index(id))<0||
           (seen&(1u<<s->id))||json_int(&j,json_get(&j,p,"delay_ms"),&s->delay)||s->delay<0||s->delay>60000||
           json_bool(&j,json_get(&j,p,"enabled"),&s->enabled))goto done;
        seen|=1u<<s->id;p=j.t[p].next;
    }
    if(schema==1)migrate_v1();
    if(cfg.steps[0].id!=NANODNS||!cfg.steps[0].enabled||cfg.steps[1].id!=KSTUFF)goto done;
    rc=0;
done:
    /* Free tokens, but leave input ownership to caller. */
    j.text=NULL;json_free(&j);return rc;
}
static int api_json(const char *method,const char *route,const char *body,int timeout,Json *j,int *uncertain) {
    Http r;*j=(Json){0};int rc=http_call(port,method,route,body,timeout,&r);
    if(uncertain)*uncertain=r.sent&&(rc||r.status>=500);
    if(rc||r.status!=200){logmsg("API %s %s: %s, HTTP %d",method,route,rc?"transport failure":"rejected",r.status);http_free(&r);return -1;}
    if(json_parse(j,r.body)){logmsg("API returned malformed/oversized JSON: %s",route);if(uncertain)*uncertain=r.sent;http_free(&r);return -1;}
    r.body=NULL;http_free(&r);return 0;
}
static int action_ok(const char *route,const char *body,int timeout,Json *j,int *uncertain) {
    if(api_json("POST",route,body,timeout,j,uncertain))return -1;
    int ok=0,invalid=json_bool(j,json_get(j,0,"ok"),&ok);
    if(invalid||!ok){if(invalid&&uncertain)*uncertain=1;logmsg("PM declined action: %s",route);json_free(j);return -1;}
    return 0;
}
static int wait_pm(Json *settings) {
    long long end=clock_ms()+cfg.ready_ms;
    do {if(!api_json("GET","/get_config",NULL,cfg.api_ms,settings,NULL))return 0;pause_ms(200);}while(clock_ms()<end);
    return -1;
}
static int check_autoload(const Json *settings,const Json *installed) {
    int enabled=0;if(json_bool(settings,json_get(settings,0,"AUTOLOAD_ENABLED"),&enabled))return -1;
    if(!enabled)return 0;
    char list[4096];if(get_string(settings,0,"AUTOLOAD_LIST",list,sizeof(list)))return -1;
    int n=0;char *save=NULL;
    for(char *s=strtok_r(list,",",&save);s;s=strtok_r(NULL,",",&save)){
        while(isspace((unsigned char)*s))s++;
        char *end=s+strlen(s);while(end>s&&isspace((unsigned char)end[-1]))*--end=0;
        if(!*s||*s=='!')continue;
        n++;
        int is_self=!strcmp(s,"pm-autoupdate.elf")||!strcmp(s,"/data/pldmgr/pm-autoupdate.elf")||!strcmp(s,"local/pm-autoupdate");
        int a=json_get(installed,0,"items");
        if(a>=0&&installed->t[a].type=='[')for(int p=a+1;p<installed->t[a].next;p=installed->t[p].next){
            if(json_eq(installed,json_get(installed,p,"filename"),"pm-autoupdate.elf")&&
               (json_eq(installed,json_get(installed,p,"slot"),s)||json_eq(installed,json_get(installed,p,"path"),s)))is_self=1;
        }
        if(!is_self)return -1;
    }
    return n<=1?0:-1;
}
static int item_to_installed(const Json *j,int p,Installed *out,int own) {
    Installed x={0};
    if(get_string(j,p,"path",x.path,sizeof(x.path))||get_string(j,p,"slot",x.slot,sizeof(x.slot))||!valid_elf(x.path))return -1;
    (void)get_string(j,p,"version",x.version,sizeof(x.version));
    (void)get_string(j,p,"checksum",x.hash,sizeof(x.hash));
    if(json_eq(j,json_get(j,p,"source_url"),cfg.source) && x.hash[0]){
        char actual[65];
        if(compute_sha256_file(x.path,actual) || strcasecmp(actual,x.hash)){
            logmsg("Ignoring damaged managed file %s",x.path);return -1;
        }
    }
    x.own=own;*out=x;return 0;
}
static int resolve_ref(const Json *j,const char *ref,Installed *out) {
    int a=json_get(j,0,"items");if(a<0||j->t[a].type!='[')return -1;
    for(int p=a+1;p<j->t[a].next;p=j->t[p].next){
        if(json_eq(j,json_get(j,p,"slot"),ref)||json_eq(j,json_get(j,p,"path"),ref)||json_eq(j,json_get(j,p,"filename"),ref))return item_to_installed(j,p,out,0);
    }
    if(ref[0]=='/'&&valid_elf(ref)){memset(out,0,sizeof(*out));snprintf(out->path,sizeof(out->path),"%s",ref);return 0;}
    /* Uploaded/imported stable basename can live in a local PM slot. */
    const char *base=strrchr(ref,'/');base=base?base+1:ref;int found=0;Installed candidate={0};
    for(int p=a+1;p<j->t[a].next;p=j->t[p].next)if(json_eq(j,json_get(j,p,"kind"),"local")&&json_eq(j,json_get(j,p,"filename"),base)){
        if(item_to_installed(j,p,&candidate,0))continue;
        if(++found>1)return -1;
    }
    if(found){*out=candidate;return 0;}return -1;
}
static int private_kstuff_name(const char *name) {
    const char *ext=strrchr(name,'.');
    return !strncasecmp(name,"kstuff",6) && isdigit((unsigned char)name[6]) &&
           strstr(name,"-fpkg-dr-") && ext && !strcasecmp(ext,".elf");
}
static int select_kstuff(const Json *j,Installed *out) {
    if(!resolve_ref(j,cfg.kstuff,out))return 0;
    /* An explicit custom reference wins, even if currently missing. */
    if(strcmp(cfg.kstuff,"/data/pldmgr/kstuff.elf"))return -1;
    Installed unique={0};
    int a=json_get(j,0,"items");
    if(a<0 || j->t[a].type!='[')return -1;
    for(int p=a+1;p<j->t[a].next;p=j->t[p].next){
        char name[256];Installed entry;
        if(!json_eq(j,json_get(j,p,"kind"),"local") ||
           get_string(j,p,"filename",name,sizeof(name)) || !private_kstuff_name(name) ||
           item_to_installed(j,p,&entry,0))continue;
        if(unique.path[0] && strcmp(unique.path,entry.path))goto ambiguous;
        unique=entry;
    }
    DIR *dir=opendir("/data/pldmgr");
    if(dir){
        struct dirent *entry;
        while((entry=readdir(dir))){
            if(!private_kstuff_name(entry->d_name))continue;
            char path[512];
            snprintf(path,sizeof(path),"/data/pldmgr/%s",entry->d_name);
            if(!valid_elf(path))continue;
            if(unique.path[0] && strcmp(unique.path,path)){closedir(dir);goto ambiguous;}
            snprintf(unique.path,sizeof(unique.path),"%s",path);
        }
        closedir(dir);
    }
    if(!unique.path[0])return -1;
    *out=unique;return 0;
ambiguous:
    logmsg("Several local kstuff builds; set local_kstuff to the intended file");
    return -1;
}
static int matches_item(const Json *j,int item,int id) {
    char key[160],name[256];
    snprintf(key,sizeof(key),"aio-%s",ids[id]);
    if(json_eq(j,json_get(j,item,"id"),ids[id]) || json_eq(j,json_get(j,item,"id"),key))return 1;
    if(id==DUMP_FORGE && json_eq(j,json_get(j,item,"id"),"ps5-dump-forge"))return 1;
    if(get_string(j,item,"filename",name,sizeof(name)))return 0;
    if(*basenames[id] && !strcasecmp(name,basenames[id]))return 1;
    if(id==ELFLDR)return !strcasecmp(name,"elfldr.elf");
    if(id==FTPSRV)return !strcasecmp(name,"ftpsrv.elf");
    if(id==WEBSRV)return !strcasecmp(name,"websrv.elf");
    char *ext=strrchr(name,'.');
    if(!ext || strcasecmp(ext,".elf"))return 0;
    *ext=0;
    if(id==DUMP_FORGE)return !strcasecmp(name,"dump-forge") || !strcasecmp(name,"ps5-dump-forge") ||
        (!strncasecmp(name,"ps5-dump-forge-",15) && strlen(name)>19 && !strcasecmp(name+strlen(name)-4,"-ps5"));
    if(id==YT_BLOCKER)return !strcasecmp(name,"YT-Blocker") || !strncasecmp(name,"YT-Blocker_v",12);
    return 0;
}
static int select_installed(const Json *j,int id,Installed *out) {
    *out=(Installed){0};
    if(id==KSTUFF)return select_kstuff(j,out); /* No remote kstuff matching. */
    int a=json_get(j,0,"items");if(a<0||j->t[a].type!='[')return -1;
    int count=0;Installed candidate={0};
    for(int p=a+1;p<j->t[a].next;p=j->t[p].next){
        if(json_eq(j,json_get(j,p,"id"),ids[id])&&json_eq(j,json_get(j,p,"source_url"),cfg.source)){
            if(item_to_installed(j,p,&candidate,1))continue;
            if(++count>1)return -1;
        }
    }
    if(count){*out=candidate;return 0;}
    if(id==0&&!resolve_ref(j,cfg.dns,out))return 0;
    count=0;
    for(int p=a+1;p<j->t[a].next;p=j->t[p].next){
        int match=matches_item(j,p,id);
        if(match&&!item_to_installed(j,p,&candidate,0)){if(++count>1)return -1;}
    }
    if(count){*out=candidate;return 0;}
    char suffix[128];snprintf(suffix,sizeof(suffix),"fallback/%s.elf",ids[id]);
    if(!path_join(out->path,sizeof(out->path),suffix)&&valid_elf(out->path)){
        out->needs_slot=1;return 0;
    }
    out->path[0]=0;return -1;
}
/* An imported copy may already match even if multiple repositories have
 * entries for the same ID. Prefer a byte-for-byte match to a new download. */
static void prefer_matching_import(const Json *list,int id,const char *hash,Installed *chosen) {
    if(chosen->own)return;
    int items=json_get(list,0,"items");
    if(items<0 || list->t[items].type!='[')return;
    for(int p=items+1;p<list->t[items].next;p=list->t[p].next){
        Installed candidate={0};
        char actual[65];
        if(json_eq(list,json_get(list,p,"source_url"),cfg.source) || !matches_item(list,p,id) ||
           item_to_installed(list,p,&candidate,0))continue;
        if(!compute_sha256_file(candidate.path,actual) && !strcasecmp(actual,hash)){
            *chosen=candidate;return;
        }
    }
}
static int launch(const char *id,const char *path) {
    if(!valid_elf(path)){logmsg("Missing/invalid local ELF: %s (%s)",id,path);return -1;}
    char encoded[1536],route[1600];if(url_encode(path,encoded,sizeof(encoded)))return -1;
    snprintf(route,sizeof(route),"/loadpayload:%s",encoded);
    Http r;int failed=http_call(port,"POST",route,NULL,cfg.launch_ms,&r);
    int ok=!failed&&r.status==200&&r.body&&!strcmp(r.body,"OK");
    logmsg("Launch %s: %s; %s",id,ok?"transferred to elfldr":"failed or outcome unknown",path);
    http_free(&r);return ok?0:-1; /* Never retry a possibly executed payload. */
}
static int dns_ready(void) {
#ifdef PM_HOST_TEST
    const char *test=getenv("PM_TEST_DNS");if(test)return !strcmp(test,"1");
#endif
    /* Bounded UDP query to the configured localhost resolver, no libc DNS wait. */
    unsigned char q[]={0x50,0x4d,1,0,0,1,0,0,0,0,0,0,3,'r','a','w',17,'g','i','t','h','u','b','u','s','e','r','c','o','n','t','e','n','t',3,'c','o','m',0,0,1,0,1};
    uint16_t id=(uint16_t)(clock_ms()^(long long)getpid());q[0]=(unsigned char)(id>>8);q[1]=(unsigned char)id;
    int fd=socket(AF_INET,SOCK_DGRAM,0);if(fd<0)return 0;
    struct sockaddr_in addr={0};addr.sin_family=AF_INET;addr.sin_port=htons(53);addr.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    if(connect(fd,(struct sockaddr*)&addr,sizeof(addr))){close(fd);return 0;}
    long long end=clock_ms()+cfg.dns_ms;int ok=0;
    do {
        if(send(fd,q,sizeof(q),0)!=(ssize_t)sizeof(q))break;
        long long left=end-clock_ms();if(left<=0)break;
        struct pollfd p={fd,POLLIN,0};int r=poll(&p,1,(int)(left>500?500:left));
        if(r>0&&(p.revents&POLLIN)){
            unsigned char b[4096];ssize_t n=recv(fd,b,sizeof(b),0);
            if(n>=12&&b[0]==q[0]&&b[1]==q[1]&&(b[2]&0x80)&&!(b[2]&2)&&!(b[3]&15)&&(b[6]||b[7])){ok=1;break;}
        }
    }while(clock_ms()<end);
    close(fd);return ok;
}
static int ensure_source(const Json *settings) {
    Json j;int present=0;
    if(api_json("GET","/sources_list",NULL,cfg.api_ms,&j,NULL))return -1;
    int a=json_get(&j,0,"sources");
    if(a>=0&&j.t[a].type=='[')for(int p=a+1;p<j.t[a].next;p=j.t[p].next)if(json_eq(&j,json_get(&j,p,"url"),cfg.source))present=1;
    json_free(&j);
    if(!present){char url[3072],route[3200];if(url_encode(cfg.source,url,sizeof(url)))return -1;
        snprintf(route,sizeof(route),"/sources_add?url=%s",url);
        if(action_ok(route,NULL,cfg.refresh_ms,&j,NULL))return -1;
        json_free(&j);logmsg("Added custom source to PM");}
    int multi=0;if(json_bool(settings,json_get(settings,0,"MULTI_SOURCES_ENABLED"),&multi))return -1;
    if(!multi){
        Http r;int failed=http_call(port,"POST","/set_config","{\"MULTI_SOURCES_ENABLED\":true}",cfg.api_ms,&r);
        int ok=!failed&&r.status==200&&r.body&&!strcmp(r.body,"OK");http_free(&r);if(!ok)return -1;
    }
    return 0;
}
static int hash_valid(const char *s) {if(strlen(s)!=64)return 0;for(;*s;s++)if(!isxdigit((unsigned char)*s))return 0;return 1;}
static int refresh_catalog(Available out[COUNT]) {
    Json j;if(api_json("POST","/repository_refresh",NULL,cfg.refresh_ms,&j,NULL))return -1;
    int a=json_get(&j,0,"sources"),found=0,rc=-1;
    if(a<0||j.t[a].type!='[')goto done;
    for(int p=a+1;p<j.t[a].next;p=j.t[p].next){
        if(!json_eq(&j,json_get(&j,p,"url"),cfg.source))continue;
        if(++found>1)goto done;
        int error=1;if(json_bool(&j,json_get(&j,p,"error"),&error)||error){logmsg("Catalog refresh failed; refusing stale catalog updates");goto done;}
        int b=json_get(&j,p,"payloads");if(b<0||j.t[b].type!='[')goto done;
        for(int q=b+1;q<j.t[b].next;q=j.t[q].next){
            char id[128],url[1024];if(get_string(&j,q,"id",id,sizeof(id)))goto done;
            int index=id_index(id);if(index<0||index==1)continue;
            Available *v=&out[index];
            if(v->present||get_string(&j,q,"version",v->version,sizeof(v->version))||!v->version[0]||
               get_string(&j,q,"checksum",v->hash,sizeof(v->hash))||!hash_valid(v->hash)||
               get_string(&j,q,"url",url,sizeof(url))||strncmp(url,"https://github.com/",19))goto done;
            v->present=1;
        }
    }
    if(found!=1)goto done;
    for(int i=0;i<COUNT;i++)if(i!=1&&!out[i].present)goto done;
    rc=0;
done:
    json_free(&j);return rc;
}
static int update_payload(int id,const Available *available,Installed *installed,int gap,long long *last_install) {
    /* PM repo metadata was verified against disk when selecting the item.
     * An imported/local item may have no checksum metadata at all. */
    char actual[65];
    if(installed->path[0] && !installed->needs_slot){
        const char *hash=installed->hash;
        if(!installed->own || !hash[0])
            hash=!compute_sha256_file(installed->path,actual)?actual:"";
        if(!strcasecmp(hash,available->hash)){
            logmsg("Unchanged: %s %s",ids[id],available->version);return 0;
        }
    }
    char backup[512]="";
    if(installed->path[0]&&!installed->needs_slot&&backup_elf(id,installed->path,backup,sizeof(backup))){logmsg("Cannot preserve previous %s; skipping update",ids[id]);problems++;return 0;}
    char url[3072],route[3400];if(url_encode(cfg.source,url,sizeof(url)))return -1;
    /* mode=replace replaces only this source's slot. No replace_slot is sent:
     * local imports and slots from other sources are never deleted/remapped. */
    snprintf(route,sizeof(route),"/repository_install?source_url=%s&id=%s&mode=replace",url,ids[id]);
    Json j;int uncertain=0;logmsg("Installing %s %s via PM",ids[id],available->version);
    wait_gap(*last_install,gap);
    int rc=action_ok(route,NULL,cfg.install_ms,&j,&uncertain);
    *last_install=clock_ms();
    if(!rc){json_free(&j);Json fresh;
        if(!api_json("GET","/list_payloads",NULL,cfg.api_ms,&fresh,NULL)){
            Installed now={0};int ok=!select_installed(&fresh,id,&now)&&now.own&&!strcasecmp(now.hash,available->hash);
            json_free(&fresh);
            if(ok){*installed=now;updates++;logmsg("Installed: %s %s",ids[id],now.version);return 0;}
        }
        uncertain=1;logmsg("Install result could not be verified against the checked catalog");
    }
    problems++;
    if(backup[0]){snprintf(installed->path,sizeof(installed->path),"%s",backup);installed->slot[0]=0;installed->own=0;}
    else if(!installed->needs_slot)installed->path[0]=0;
    if(uncertain){logmsg("PM may still finish installation; use saved ELF for this boot and stop issuing installs");return -1;}
    logmsg("Using previous local %s after rejected/failed update",ids[id]);return 0;
}
static int boot_identity(char *out,size_t cap) {
#ifdef PM_HOST_TEST
    const char *id=getenv("PM_TEST_BOOT");if(!id)id="host-test-boot";
    return snprintf(out,cap,"%s",id)>=(int)cap?-1:0;
#else
    struct timeval tv;size_t size=sizeof(tv);int mib[2]={CTL_KERN,KERN_BOOTTIME};
    if(sysctl(mib,2,&tv,&size,NULL,0)||size!=sizeof(tv))return -1;
    return snprintf(out,cap,"%lld.%06ld",(long long)tv.tv_sec,(long)tv.tv_usec)>=(int)cap?-1:0;
#endif
}
static int youtube_closed(void) {
#ifdef PM_HOST_TEST
    const char *flag=getenv("PM_TEST_YOUTUBE_FLAG");
    if(flag)return !access(flag,F_OK);
    const char *v=getenv("PM_TEST_YOUTUBE_CLOSED");return !v||!strcmp(v,"1");
#else
    typedef struct { uint32_t app_id;uint64_t unknown1;char title_id[14];char unknown2[0x3c]; } AppInfo;
    extern int sceKernelGetAppInfo(pid_t,AppInfo*);
    Json j;if(api_json("GET","/processes_list",NULL,cfg.api_ms,&j,NULL))return 0;
    int a=json_get(&j,0,"processes"),safe=1;
    if(a<0||j.t[a].type!='['||!j.t[a].children){json_free(&j);return 0;}
    for(int p=a+1;p<j.t[a].next;p=j.t[p].next){int pid;char name[128];
        if(json_int(&j,json_get(&j,p,"pid"),&pid)||get_string(&j,p,"name",name,sizeof(name))){safe=0;break;}
        AppInfo info={0};
        if(sceKernelGetAppInfo((pid_t)pid,&info)){if(!strcmp(name,"eboot.bin"))safe=0;continue;}
        if(!strncmp(info.title_id,"PPSA01650",9)||!strncmp(info.title_id,"PPSA01651",9)||!strncmp(info.title_id,"PPSA01652",9)){safe=0;break;}
    }
    json_free(&j);return safe;
#endif
}
static void write_status(const char *phase) {
    char path[1024],text[512];if(path_join(path,sizeof(path),"status.json"))return;
    snprintf(text,sizeof(text),"{\"updater_version\":\"%s\",\"phase\":\"%s\",\"updated\":%d,\"problems\":%d}\n",PM_UPDATER_VERSION,phase,updates,problems);
    if(atomic_text(path,text))logmsg("Cannot write status.json");
}
/* Persist only an unattempted blocker. Clear the record before dispatch, so
 * a lost /loadpayload reply can never cause a second application of its patches. */
static int read_pending_yt(const char *record,const char *boot,char path[512]) {
    char *text=read_text(record,1024),id[128];
    int prior_updates,prior_problems;
    int ok=text && sscanf(text,"%127[^\n]\n%d\n%d\n%511[^\n]",id,&prior_updates,&prior_problems,path)==4
           && !strcmp(id,boot) && path[0]=='/';
    if(ok){updates=prior_updates;problems=prior_problems;}
    free(text);return ok;
}
static int deliver_yt(const char *record,const char *boot,const char *path) {
    if(!youtube_closed()){
        char text[1024];
        if(strpbrk(path,"\r\n"))return -1;
        snprintf(text,sizeof(text),"%s\n%d\n%d\n%s",boot,updates,problems,path);
        if(atomic_text(record,text))return -1;
        write_status("waiting_youtube");
        notify("Close YouTube for YT Blocker. Waiting up to one minute.");
#ifdef PM_HOST_TEST
        const int window=180,interval=20;
#else
        const int window=60000,interval=2000;
#endif
        long long end=clock_ms()+window;
        for(;;){
            pause_ms(interval);
            if(youtube_closed())break;
            if(clock_ms()>=end){
                notify("YT Blocker pending. After closing YouTube, run PM AutoUpdate again.");
                return 1;
            }
        }
    }
    if(unlink(record) && errno!=ENOENT)return -1;
    return launch(ids[YT_BLOCKER],path);
}
int main(void) {
    signal(SIGPIPE,SIG_IGN);
    const char *config_path="/data/pldmgr/pm-autoupdate.json";
#ifdef PM_HOST_TEST
    const char *e=getenv("PM_CONFIG");if(e)config_path=e;
    e=getenv("PM_STATE_DIR");if(e)snprintf(state_dir,sizeof(state_dir),"%s",e);
    e=getenv("PM_PORT");if(e){port=atoi(e);if(port<1||port>65535)return 2;}
#endif
    char *text=read_text(config_path,65536);
    if(!text){if(errno!=ENOENT){notify("Cannot read configuration; stopped");return 2;}text=strdup(default_config);}
    if(!text||parse_config(text)){free(text);notify("Invalid pm-autoupdate.json; stopped");return 2;}free(text);
    if(mkdir(state_dir,0755)&&errno!=EEXIST){notify("Cannot create updater directory");return 2;}
    char path[1024];if(path_join(path,sizeof(path),"lock"))return 2;
    int lock=open(path,O_CREAT|O_RDWR,0600);if(lock<0)return 2;
    if(flock(lock,LOCK_EX|LOCK_NB)){close(lock);notify("Another updater is running");return 0;}
    path_join(path,sizeof(path),"fallback");if(mkdir(path,0755)&&errno!=EEXIST){close(lock);return 2;}
    int result=1;Json settings={0},installed_json={0};Installed installed[COUNT]={0};
    char boot[128],marker[1024],yt_record[1024];
    if(path_join(yt_record,sizeof(yt_record),"pending-yt.txt"))goto done;
    if(boot_identity(boot,sizeof(boot))||path_join(marker,sizeof(marker),"started-boot.txt")){notify("Cannot identify boot safely; stopped");goto done;}
    text=read_text(marker,256);
    int started=text && !strcmp(text,boot);free(text);
    if(started){
        char pending_path[512];
        if(!read_pending_yt(yt_record,boot,pending_path)){
            notify("Payload sequence already started this boot");result=0;goto done;
        }
        path_join(path,sizeof(path),"last.log");logfile=fopen(path,"a");
        /* Reopening after Y2JB closes YouTube resumes only the unsent last payload. */
        int enabled=0;
        for(int i=0;i<COUNT;i++)if(cfg.steps[i].id==YT_BLOCKER)enabled=cfg.steps[i].enabled;
        if(!enabled){notify("Pending YT Blocker is disabled in configuration");result=0;goto done;}
        if(wait_pm(&settings)){notify("PM unavailable; YT Blocker remains pending");result=0;goto done;}
        int sent=deliver_yt(yt_record,boot,pending_path);
        if(sent<0){notify("YT Blocker transfer failed or unknown; reboot before retrying");goto done;}
        if(!sent){write_status("done");notify("YT Blocker sent. Boot sequence complete.");}
        result=0;goto done;
    }
    path_join(path,sizeof(path),"last.log");logfile=fopen(path,"w");
    logmsg("PM AutoUpdate %s; native PM API, local-only kstuff",PM_UPDATER_VERSION);
    if(wait_pm(&settings)||api_json("GET","/list_payloads",NULL,cfg.api_ms,&installed_json,NULL)){notify("PM API unavailable; no payloads started");goto done;}
    if(check_autoload(&settings,&installed_json)){notify("Keep only pm-autoupdate.elf in PM Autoload; stopped to avoid duplicate launches");goto done;}
    (void)select_installed(&installed_json,NANODNS,&installed[NANODNS]);
    write_status("dns");
    if(!installed[NANODNS].path[0] && materialize_dns(&installed[NANODNS])){
        notify("Cannot prepare first-boot nanoDNS; see last.log");goto done;
    }
    char dns_marker[1024],pending[160];
    if(path_join(dns_marker,sizeof(dns_marker),"dns-boot.txt"))goto done;
    snprintf(pending,sizeof(pending),"pending-%s",boot);
    text=read_text(dns_marker,256);
    if(text && !strcmp(text,pending)){
        free(text);notify("Previous nanoDNS delivery is uncertain; reboot before retrying");goto done;
    }
    int already_sent=text&&!strcmp(text,boot);free(text);
    if(!already_sent){
        /* A lost reply may still have launched nanoDNS. Never send it twice on a retry. */
        if(atomic_text(dns_marker,pending)){notify("Cannot record nanoDNS boot marker");goto done;}
        if(launch("nanodns",installed[NANODNS].path)){
            notify("nanoDNS transfer failed or unknown; reboot before retrying");goto done;
        }
        if(atomic_text(dns_marker,boot)){notify("Cannot finalize nanoDNS boot marker");goto done;}
    } else logmsg("nanoDNS was already sent this boot");
    long long last_launch=clock_ms();
    pause_ms(cfg.steps[0].delay);
    int online=cfg.auto_update&&dns_ready();
    write_status("checking");
    if(!online)logmsg("Update disabled or localhost DNS did not resolve in time; using local payloads");
    long long update_deadline=clock_ms()+cfg.budget_ms;
    Available available[COUNT]={0};
    if(online&&(ensure_source(&settings)||refresh_catalog(available))){online=0;problems++;logmsg("Source unavailable; using local payloads");}
    for(int i=1;i<COUNT;i++)(void)select_installed(&installed_json,i,&installed[i]);
    if(online){
        write_status("updating");
        long long last_install=last_launch;
        for(int i=0;i<COUNT;i++){Step *s=&cfg.steps[i];if(!s->enabled||s->id==1)continue;
            if(clock_ms()>=update_deadline){logmsg("Update budget reached; remaining payloads stay local");problems++;break;}
            prefer_matching_import(&installed_json,s->id,available[s->id].hash,&installed[s->id]);
            int gap=i?cfg.steps[i-1].delay:0;
            if(update_payload(s->id,&available[s->id],&installed[s->id],gap,&last_install))break;
        }
    }
    json_free(&settings);
    /* Every operation above finishes or selects immutable fallback before this point. */
    if(atomic_text(marker,boot)){notify("Cannot record boot; stopped to prevent repeated kernel payloads");goto done;}
    write_status("launching");
    int yt_pending=0;
    for(int i=1;i<COUNT;i++){
        Step *s=&cfg.steps[i];if(!s->enabled)continue;
        if(!valid_elf(installed[s->id].path)){
            logmsg("Skipping missing %s (%s)",ids[s->id],s->id==KSTUFF?cfg.kstuff:"no installed ELF");
            problems++;continue;
        }
        wait_gap(last_launch,cfg.steps[i-1].delay);
        int sent=s->id==YT_BLOCKER ? deliver_yt(yt_record,boot,installed[s->id].path)
                                   : launch(ids[s->id],installed[s->id].path);
        if(sent<0){problems++;notify("Payload transfer failed; sequence stopped. Reboot before retrying");goto done;}
        if(sent>0){yt_pending=1;continue;}
        last_launch=clock_ms();
    }
    result=0;
    if(yt_pending){write_status("waiting_youtube");goto done;}
    write_status("done");
    char summary[256];snprintf(summary,sizeof(summary),"Finished: %d updated, %d warning(s). nanoDNS updates apply next boot.",updates,problems);notify(summary);
done:
    json_free(&settings);json_free(&installed_json);
    if(result)write_status("stopped");
    if(logfile)fclose(logfile);
    flock(lock,LOCK_UN);close(lock);return result;
}
