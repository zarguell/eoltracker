import{y as S,C as _,t as g,aO as b,ae as v,af as T,ar as m}from"./theme.BMulice8.js";import{d as L,aB as w,o as t,c as u,F as P,y as e,N as k,p as s,Y as C,n as o,O as E,E as d,u as f,b as B,_ as x}from"./framework.DtgILcqN.js";const p="/assets/banner.G4t4cYQ4.jpg",V="/assets/img-en1.BdH61YSz.jpg",j="/assets/img-en2.DrBUyz0V.jpg",D={banner:p,overall:`# 1、openEuler Community Version Lifecycle Management (Overall)

Community releases are named based on the release year and month. For example, openEuler 20.09 was released in September 2020.

Community releases include Long Term Support (LTS) and innovation releases.

- **LTS releases (effective from August 2025):** Released every 4 years with 4 years of community support. The latest openEuler 24.03 LTS was released in June 2024 (kernel 6.6). New LTS releases are launched in March of even-numbered years, followed by SP updates in December of even-numbered years, and June (optional) and December of odd-numbered years.
- **Innovation releases (effective from August 2025):** Released in September every year with 6 months of community support."
`,img1:V,lts:`# 2、openEuler Community Version Lifecycle Management (LTS+SP)

#### Lifecycle management (effective from August 2025):

1. **The full lifecycle of an LTS release** is 6 years (4 years of full support and 2 years of maintenance support). Prior to the end of this lifecycle, **a joint maintenance team may be assembled** to request an optional 2-year extension. The end of the lifecycle of any release will be notified by email and public announcement 3 months in advance.
2. In principle, the lifecycle for service pack (SP) updates within an LTS release is 9 months for minor SPs (released in June, optional) or 24 months for major SPs (released in December). Major SPs are recommended for **large-scale use**.
3. By default, the lifecycle of an initial LTS release (SP0) **follows that of a major SP**, but could end half a year to 1 year in advance based on a review of its usage in the community and community rules. SP7, as the final SP for an LTS release, concludes with the full lifecycle of the LTS release.
4. Full support includes fixes for CVEs and bugs, support for new hardware, and some new features with backward compatibility within the LTS release. Maintenance or extended support is limited to fixes for critical or high-severity CVEs and bugs."

*The scheme has been reported to the Technical Committee and the Release SIG and publicly announced in the community mailing list.
`,img2:j},z="/assets/img-zh1.5e7Dt6nO.jpg",I="/assets/img-zh2.J2Y_aumJ.jpg",M={banner:p,overall:`# 1、openEuler社区版本生命周期管理规范（总体）

社区版本按照交付年份和月份进行版本号命名。例如，openEuler 20.09 于2020年09月发布。

社区版本分为长期支持版本和创新版本。

- **长期支持版本（自25年8月起生效）：** 发布间隔周期定为4年，提供4年社区支持。社区当前主力LTS版本openEuler 24.03 LTS于24年6月发布（基于6.6内核）。偶数年3月发布新一代LTS首版本，偶数年12月，奇数年6月(可选)、12月发布对应SP版本。
- **社区创新版本（自25年8月起生效）：** openEuler每隔12个月会发布一个社区创新版本，提供6个月社区支持。9月发布创新版本。
`,img1:z,lts:`# 2、openEuler社区版本生命周期管理规范（LTS+SP）

#### 生命周期规则（自25年8月起生效）：

1. LTS版本**全版本**生命周期6年(4+2)，到生命周期结束前由**相关团队组建联合维护团队**，申请延长至8年(+2可选)，单个版本生命周结束前，以邮件和公告的方式提前3个月知会。
2. LTS 版本 SP 版本生命周期原则上按照小 SP（6月份 Release，可选） 9个月，大 SP（12月份 Release） 24 个月执行；**大规模使用**建议选择大 SP。
3. SP0 **默认执行大 SP 策略**，可基于社区使用情况和社区规则提前半年~1年审视是否提前结束；SP7 作为 LTS 最后一个 SP，随 LTS 全版本生命周期结束。
4. 全面支持：CVE、Bugfix，新硬件支持和少量新特性（保证LTS内前向兼容的情况）。维护支持/扩展支持：修复"主要"以上CVE和Bug 。

*方案已经在TC和Release SIG汇报，并完成了社区邮件列表公示。
`,img2:I},a={en:D,zh:M},R={key:1,class:"mo-banner"},F={class:"mo-title"},J={class:"lifecycle-markdown"},O={class:"markdown-new"},A={class:"markdown-new markdown-lts"},N=L({__name:"TheLifecycle",setup(Y){const{locale:n,t:r}=S(),{lePadV:y}=_(),h=g(),l=B(()=>h.theme==="dark"),i=new b({html:!0,linkify:!0});return(G,$)=>{const c=w("dompurify-html");return t(),u(P,null,[e(y)?(t(),u("div",R,[s("p",F,C(e(r)("lifecycle.title")),1)])):(t(),k(v,{key:0,class:"lifecycle-banner",title:e(r)("lifecycle.title"),"background-image":e(a)[e(n)].banner},null,8,["title","background-image"])),o(T,null,{default:E(()=>[s("div",J,[d(s("div",O,null,512),[[c,e(i).render(e(a)[e(n)].overall)]]),o(e(m),{src:e(a)[e(n)].img1,class:f({"figure-dark":l.value})},null,8,["src","class"]),d(s("div",A,null,512),[[c,e(i).render(e(a)[e(n)].lts)]]),o(e(m),{src:e(a)[e(n)].img2,class:f({"figure-dark":l.value})},null,8,["src","class"])])]),_:1})],64)}}}),Q=x(N,[["__scopeId","data-v-711cd73f"]]);export{Q as T};
