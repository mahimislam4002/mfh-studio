# Grok-কে দেওয়ার নির্দেশনা: Ultimate Second Brain

এই প্যাকেজে থাকা `preview.html`-কে UX ও visual direction হিসেবে দেখে আমার বর্তমান ওয়েবসাইটে **Ultimate Second Brain** ফিচারটি সম্পূর্ণভাবে তৈরি করো। এটি এক পাতার ড্যাশবোর্ডে সবকিছু গুঁজে দেওয়ার কাজ নয়। আমার Notion reference-এর আলাদা পেজ, ডেটাবেস, ভিউ, সম্পর্ক এবং কাজের প্রবাহ বজায় রেখে ওয়েবসাইটের নিজস্ব UI, backend ও database-এ বাস্তবভাবে কাজ করাও। আগে repository-এর বর্তমান কাঠামো, framework, authentication, data model, design system ও বিদ্যমান Second Brain-সংক্রান্ত code পরীক্ষা করো; তারপর একই stack ও conventions অনুসরণ করে implement করো। বিদ্যমান অন্য ফিচার ভেঙে দিও না।

## Product goal

ব্যবহারকারী যেন দ্রুত তথ্য capture করতে পারে, পরে সেগুলো process করে task/note/idea বানাতে পারে, এবং dashboard থেকে আজকের কাজ, projects, goals, habits, planner ও content workflow চালাতে পারে। এটি Notion-এর মতো সম্পর্কযুক্ত workspace হবে; বাস্তব তথ্য সংরক্ষণ, সম্পাদনা, search, filter, status update এবং export কাজ করতে হবে। শুধু দেখতে সুন্দর mockup, dead button, placeholder link বা browser-only demo storage গ্রহণযোগ্য নয়।

## প্যাকেজ ব্যবহার

- `preview.html` একটি standalone clickable UI reference। Sidebar-এর পৃথক screen ও preview interaction দেখে layout, spacing, cards, tables, board, modal এবং responsive আচরণ অনুসরণ করো।
- সর্বশেষ visual direction হলো user-এর দেওয়া Grok screenshot: dark navy sidebar; light cool-gray main canvas; বড় navy-to-violet gradient hero; rounded pill section navigation; dark saturated metric cards; spacious white panels; refined borders, shadows, clear color grading and readable type. `preview.html`-এর সর্বশেষ pass-এ এই direction দেখানো আছে। আগের sage/green look অনুসরণ কোরো না। Sidebar-এর নিচে User Guide, তার নিচে All Databases, এবং শেষে Settings & Export থাকবে।
- Dashboard-এর hero-এর নিচে Overview / Inbox / Notes / Tasks / Projects / Goals / Areas pill navigation থাকবে। KPI cards-এ Inbox, Open Tasks, Notes, Active Projects দেখাবে এবং click করলে সংশ্লিষ্ট screen খুলবে। Today’s Focus input/save-সহ persist করবে। Areas বিভাগ Project-এর Area field অনুযায়ী প্রকল্প filter করবে।
- প্রতিটি ভেতরের পেজে header-এ history-aware **Back** button থাকতে হবে; আগের screen-এ ফিরবে, Home-এ ফিরে আসতে বাধ্য করবে না। Dashboard-এর compact nested cards-এ habit grid বা অন্য content পাশের panel-এর মধ্যে overflow/overlap করতে পারবে না। Task List / Board / Calendar view switcher-ও বাস্তবে layout বদলাবে।
- User Guide-এ শুধু ৫ ধাপের সংক্ষিপ্ত overview নয়, প্রতিটি database-এ কোন তথ্য লিখতে হবে, field-গুলোর মানে, কীভাবে ব্যবহার করতে হবে এবং তা user-কে কীভাবে সাহায্য করে—সহজ ভাষায় থাকবে। Dashboard-এ Today's Focus save করার control থাকতে হবে।
- Sidebar-কে তিনটি vertical অংশে রাখো: (1) উপরের corner-এ “Ultimate Second Brain” wordmark, fixed; (2) মাঝখানে একটিমাত্র scroll container যেখানে **Home, Plan, Capture & Learn, User Guide, All Databases, Settings & Export—সব menu group** থাকবে; (3) নিচে signed-in profile ও Exit action fixed. শুধু মাঝের menu container scroll হবে, 4–5px scrollbar সহ। নিচের tools menu item-গুলো menu scroll-এর বাইরে sticky/fixed হবে না; profile/footer যেন menu-এর ওপর না চাপে।
- Wordmark-কে top-left fixed text + small inline/CSS icon হিসেবে রাখো; giant PNG/background banner বা image overlay ব্যবহার কোরো না। User Guide-এর UI সম্পূর্ণ English-এ হবে (database names, labels, instructions, field-help copy included); browser locale independent.
- Profile name/avatar hard-code কোরো না: বর্তমান Portfolio SaaS-এর authenticated user/session থেকে display name ও profile image নাও; image না থাকলে initials fallback। “Exit to Portfolio” চাপলে Portfolio-র বিদ্যমান home/dashboard route-এ **same tab-এ** ফিরবে এবং user-কে sign out করবে না। আলাদা Sign out feature থাকলে সেটি বিদ্যমান site auth flow-ই ব্যবহার করবে।
- Portfolio SaaS-এর “Ultimate Second Brain” navigation item-এ click করলে dedicated route/interface **same tab-এ** খুলবে (`target=_self` বা existing SPA route); নতুন tab নয়। App-এর নিজের sidebar brand/title-এ click করলে app Home খুলবে। Existing authentication guard, user/workspace scoping এবং site navigation বজায় রাখো। Repository-তে route খুঁজে নাও; URL অনুমান বা নতুন parallel app বানিও না।
- প্রতিটি sidebar, dashboard pill, KPI, guide shortcut, database index link এবং Back button click করে সংশ্লিষ্ট ডান পাশের content render হচ্ছে কিনা যাচাই করো। Route handler অনুপস্থিত হলে blank pane থাকবে না—error boundary/clear recovery state দেখাও। Back navigation আগের screen-এ ফিরবে; exit link শুধু Portfolio dashboard-এ যাবে।
- Demo content কেবল উদাহরণ; production-এর data user-specific এবং server/database-এ persist হবে।
- Preview-র কোনো limitation-কে production-এর requirement মনে কোরো না। বাস্তব app-এ auth, authorization, validation, empty/loading/error state এবং persistence যোগ করো।

## আবশ্যিক navigation ও পেজ

1. **Home dashboard:** Quick Capture; Today’s Focus; due/open task; Active Projects; Goals; Habits (৬টি অভ্যাস); Daily Planner; Content Ideas preview. প্রতিটি summary-তে click করলে সংশ্লিষ্ট আসল page খুলবে।
2. **Start Here:** setup guide, daily workflow (সকাল/দিন/সন্ধ্যা) এবং weekly review workflow।
3. **Quick Capture:** thought, task, idea, link, question capture; captured date; processed/unprocessed filter; process করে সংশ্লিষ্ট record তৈরি/লিংক করা; edit/delete।
4. **Tasks:** list/board/calendar ধরনের usable view, filter/search, create/edit, done toggle, due date, priority, project relation, context।
5. **Projects:** create/edit/archive, area, status, priority, timeline, notes এবং সংশ্লিষ্ট goal/task/note দেখার relation views।
6. **Goals:** category, progress, status, target date, related projects, “Why It Matters”; progress update।
7. **Habit Tracker:** প্রতিদিনের ৬টি checkbox, তারিখভিত্তিক history এবং দৈনিক score স্বয়ংক্রিয়ভাবে গণনা।
8. **Daily Planner:** date/day, energy, gratitude, schedule notes, Top 3 priorities, wins; দৈনিক entry সংরক্ষণ ও পরে edit করা।
9. **Weekly Review:** week/date, weekly focus, key wins, lessons learned, next-week plan, rating; একাধিক সপ্তাহের history।
10. **Notes & Knowledge Base:** rich note/page body, type, tags, project relation, favorite, created date; search/filter/edit।
11. **Content Ideas Inbox:** board-এ Inbox → Scripting → Creating → Scheduled → Published; format, একাধিক platform, hook/angle, priority, publish date। Card-কে stage বদলালে persistent update হবে।
12. **Resources & Bookmarks:** URL, category, rating, status, tags; open/edit/filter/delete।
13. **All Databases:** ১০টি data area-র index, count ও direct navigation।
14. **Settings / data tools:** account/workspace scoped export; import-এ validation, duplicate handling, relation preservation। AI feature optional; server-side key/configuration, error/loading state, rate limit/privacy handling।

## Reference-এ পাওয়া database fields

- **Quick Capture:** Capture (title), Captured (created time), Processed (checkbox), Type: Thought / Task / Idea / Link / Question.
- **Tasks:** Task title, Status: Not started / In progress / Done, Priority: High / Medium / Low, Due Date, Project relation, Context: Deep Work / Quick Win / Call / Errand / Online.
- **Projects:** Name, Area: Work / Personal / Health / Finance / Learning / Business, Status: Not Started / In Progress / On Hold / Completed, Priority: High / Medium / Low, Timeline, Notes, Goals relation, Tasks relation, Notes relation.
- **Goals:** Goal, Category: Career / Health / Finance / Learning / Personal / Business, Progress %, Status: Not Started / In Progress / Achieved / Paused, Target Date, Related Projects relation, Why It Matters.
- **Habit Tracker:** Date, Day, Deep Work, Workout, Read 20 min, Meditate, Drink Water, Sleep 7h+, Score formula (completed count/6; define and display consistently).
- **Daily Planner:** Date, Day, Energy: High / Medium / Low, Gratitude, Schedule Notes, Top 3 Priorities, Wins.
- **Weekly Review:** Week, Week Of, Weekly Focus, Key Wins, Lessons Learned, Next Week Plan, Rating: Excellent / Good / Average / Tough.
- **Notes & Knowledge Base:** Title, Type: Idea / Meeting Note / Learning Note / Journal / Reference / Book Note, Tags: Work / Personal / Health / Finance / Learning / Business, Project relation, Favorite, Created, page body.
- **Content Ideas Inbox:** Idea, Format: Video / Reel-Short / Carousel / Post / Article / Thread, Platform (multi-select): YouTube / Instagram / TikTok / LinkedIn / Blog / Newsletter / X, Hook / Angle, Priority: High / Medium / Low, Publish Date, Status: Inbox / Scripting / Creating / Scheduled / Published.
- **Resources & Bookmarks:** Name, Link, Category: Article / Video / Tool / Course / Book / Podcast / Template, Rating: 5-Essential / 4-Great / 3-Useful / 2-Okay / 1-Skip, Status: To Review / In Progress / Reviewed, Tags.

## Data ও interaction requirements

- সব record authenticated user/workspace-এর সাথে scoped হবে; server-side access control নিশ্চিত করো।
- Create/read/update/delete এবং relation unlink/delete behavior স্পষ্ট, consistent ও কার্যকর করো। Confirm ছাড়া destructive bulk action নয়।
- Home/dashboard-এর সংখ্যা ও preview live database data থেকে আসবে; hard-coded demo count নয়।
- Form-এ validation, helpful errors, loading/success feedback, empty states, keyboard accessibility এবং responsive layout থাকবে।
- Search relevant database জুড়ে কাজ করবে; filter/sort state ব্যবহারযোগ্য হবে। Date ও timezone handling ধারাবাহিক রাখো।
- Habit score formula, task completion/status, content stage এবং project/goal relation সব জায়গায় consistent রাখতে হবে।
- Data export বাস্তব record ও relations ধরে; import dry-run/preview, mapping, validation, duplicate handling ও failure report দেবে। Notion API token/key browser-এ expose করবে না।
- AI generate/summarize feature repository-তে provider integration থাকলেই সংযুক্ত করো; secrets server env-এ। না থাকলে fake success দেখিও না—proper setup/error UI দেখাও।

## কাজের পদ্ধতি ও সমাপ্তির প্রতিবেদন

প্রথমে codebase inspect করে existing data model/auth/UI pattern-এর সাথে মিলিয়ে implementation plan করো। তারপর complete feature implement করো, প্রয়োজনীয় migration/API/UI update করো, এবং project-এ আগে থেকে থাকা lint/build/test/verification command চালাও। কোনো external integration বা secret না থাকলে প্রকৃত সীমাবদ্ধতা ও হাতে করতে হবে এমন configuration স্পষ্ট করে বলো; feature কাজ করছে বলে দাবি কোরো না। শেষে আমাকে জানাও:

1. কোন routes/pages, schema/API এবং interactions তৈরি হয়েছে;
2. কোন commands/verification সফল বা ব্যর্থ হয়েছে;
3. setup/env/migration/deployment-এ আমার কী করতে হবে;
4. কোন অংশ external credential বা existing backend না থাকায় অসম্পূর্ণ।

কোনো existing functionality মুছে বা unrelated redesign করে scope বাড়িও না।


