American Airlines NXOP | Neo4j - Enterprise Knowledge Graph

Sam Gardsbane with American Airlines Group Inc.
Recorded on Sep 3, 2026 via Zoom, 49m



Participants

Neo4J
Sam Gardsbane, Sr. Account Executive
Timothy Reyes, AI Solutions Architect
Yancarlo Perez, Principal Consulting Engineer
Dean Stavropoulos, Senior Solution Engineer
Jacob Dasuqi, Solutions Engineer

American Airlines Group Inc.
Amit Sahay, Technical Lead
Pablo Trevino
Praveen Chand, Principal Architect



Transcript

0:00 | Sam
enjoy competing. See you. Hey, Dean. 

0:19 | Praveen
Hello? 

0:22 | Sam
Hi, Pablo. How are you guys? We are good. You have the gamut of the Neo4J fourj team. And then from our side, we're just waiting on Sam. 

0:37 | Amit
Sounds good. I think some more of our team members are going to join too. 

0:42 | Praveen
Hey, Pablo. 

0:44 | Sam
Hey, how are you? Good? How are you? Good, good. All right. Let's see. We got Dean, we got Tim, Jake, Giancarlo's, on. I think we're waiting for some more American team members. 

1:36 | Sam
Let me send them a message yep. 

1:43 | Sam
I saw Amit accepted, Lakshmi accepted. I mean, Praveen accepted as well, so. 

1:54 | Sam
Maybe they're just walking to a room or? 

3:07 | Amit
Hey, everyone. Good afternoon. 

3:13 | Sam
Hey, Amit. 

3:35 | Sam
Waiting on Praveen and Lakshmi. 

4:29 | Praveen
Hey, Praveen. Sorry. Hi, good afternoon. Sorry… who are we having the call? 

4:38 | Sam
Everybody's on except for Lakshmi? 

4:42 | Praveen
Yeah, unfortunately, we do have a full day Aws training today, so, and most likely most of our team will not be available. Can we do a reschedule to tomorrow afternoon or Monday? 

4:57 | Sam
Our team isn't really available. This was the only time that I had given that you guys wanted to do something pretty quickly this week. Okay? You're on, Amit's on and Pablo's on the only person we're missing is Lakshmi. 

5:15 | Praveen
Okay. Then, yeah, if that's the case, let's yeah, we can move on. I thought Pablo and Amit also are not there. Okay. Let's then we are good. 

5:23 | Sam
Okay. Yeah, we'll try to keep this, you know, brief productive concise, all that good stuff. This is a follow up to our initial discussion and… we wanted to talk a little bit more about the knowledge layer. I've got one of our subject matter experts, Tim Reyes who's on the call. He leads one of… our products called neocarta, which is, I'll… let him describe it. But what I'd like to do is just for the benefit of the team, I tried to help them understand what the project is, right? Moving off of a 54 year old mainframe application to a more open architecture. And you guys recognizing the need for a knowledge or intelligence layer to go into that for agentic and AI capabilities to reduce hallucinations, represent the business better and… allow the agents to provide better output, right? More reliable output, more explainable output. And you guys have got lots of different sources of data. And so we wanted to talk a little bit more about that, talk a little bit about where we fit in the Aws stack and how we partner to give you guys a little bit more comfort level with that. So does that sound right? Or could you maybe add color to what I just described? Or correct me if I'm wrong? 

6:59 | Amit
No, Sam, I think that's the perfect introduction to get started on this one. That's exactly what we're looking for. That. How do we build the knowledge layer that serves both the business and for the it folks? Not only for the sdlc but also to generate this business outcome where we can provide explanation to the solution. So I think we should be good to go, be able to do? 

7:28 | Sam
That great. So with that, in the invite, I'd put two links. I'd put a link to our approach to a knowledge layer. That was the blog that our field CTO for AI had put out there. Did y'all have a chance to review that document at all? Or should we kind of review that from the start? 

7:55 | Amit
I could not get the chance to review that and we don't have to go through that. I mean, we can look into that in our time. But if you have, if we can talk through your approach, what you wanted to explain, that will be perfect. And we have the document we can go through for details. 

8:17 | Sam
All right. Great. So I guess maybe that's a cue for you Tim to kind of if you'd like to walk through our approach to building out a knowledge layer based upon the fact that they're going to be an Aws environment, but they've got sources from lots of different areas and maybe you can keep it interactive. And as you're describing this, we can ask questions about their different data sources, and then you can touch on how we can… leverage or inherit a lot of the work that they've done through neocarta and go from there. 

8:56 | Timothy
Yeah, that sounds great. I guess I will start off by just describing what do we mean when we say semantic layer or enterprise knowledge? You'll hear these terms. I just want to make sure we're operating from the same baseline understanding. It's this idea that you need some sort of abstraction that sits between your agents and your actual enterprise data sources. And these can be not just strict rdbms databases. These can be snowflake, these can be elasticsearch, these can be repository or an S3 bucket of PDFS. These can be your atlassian, your confluence. It's really any source of knowledge within your business that, you know, contains information that the agents could use to answer your questions, but they just don't know where it is, right? So, this semantic layer, this enterprise knowledge layer at its most basic form acts to provide a roadmap, a traversable queryable roadmap that any agent can use to say, hey, I need to ask, you know, a customer just asked me about a particular subdomain of my business. And I need to know where the data to answer that question accurately lives and how it is structured, so that I can query for it as context to then give the correct answer. That's the most basic form where it gets more powerful is the ability to persist and write back events that have transpired and that's when you're interacting with these users, when the agents are interacting with these users. So, agent number one gets asked a question, a novel question that it's never seen before. And it then queries the semantic layer and says, hey, where is the data pertaining to this question? It gets back the location, it gets back, the shape and the schema, it constructs a query and that query runs. OK, it has some performance to it. And it gets back, the data constructs an answer and gives that answer to the user and the user says, hey, that's close, but it's missing X, y and Z detail. I didn't quite get this answer or they say that's not what I'm looking for and the agent goes through this iterative process with this user the first time and a couple of queries fire with different levels of performance. Right here comes agent number two. Now, sometime later, it receives a question from a user, it performs a semantic similarity search against the graph and says, hey, have I ever seen a question like this before? The answer is, yes. OK. What steps did that previous agent execute? What was the user sentiment that came back? The number of transactions that had to take place? The number of user touches that had to take place? The performance metrics of those queries, maybe there's room for optimization. Maybe you've got a high, you know, this is what I'm looking for. But the query ran, you know, for longer than you would want within your slas. So now that agent is empowered with the ability to reuse what it wants to reuse from that previous iteration, improve upon it in places where there's opportunity for improvement. And then that gets persisted. So now we have this kind of ranking and weighting metric. OK, I've run this kind of question three four, five, six times and all six times this first step that I did that I've improved the performance of a few times. But fundamentally that step yielded a positive result from the user, right? It got the user what they were looking for, that's been improved and refined upon. I don't need to now re litigate what is the next thing? The first step that I should do when I receive this question, right? I don't have to use any tokens to decide what I need to do. I don't need to query the database schema map for where I need to go. I can just say I've seen this question before. I've got a high degree of confidence of what to do first. Based on historical precedent. I can now just act, I can copy what was done and act and then at points in that traversal as it steps through this reusable process, something that jumped out to me from your last call with Sam was this idea of what does process look like in this agentic future? This is starting to build it out organically and we can seed this graph with any existing process knowledge that you may have. We can extract business processes from it and store them in this layer as kind of your starting point. But then the agents are empowered to kind of iterate on those and refine them as they go. And then persist that knowledge back to the graph as a shared knowledge repository that all agents have access to. So now there's this reliability and reusability that's not possible with traditional agents that don't have this kind of semantic layer that they can write back to and learn from every agent's acting independently. Every action is unpredictable. Maybe they get it right? 60 percent of the time you're trying to tweak, you know, prompts to see how you can get it to answer the right way. Every single time. What you can do instead is the semantic layer approach, this enterprise knowledge layer approach. There's a lot more that can be added to it. I'm starting. At a higher level, but that's kind of your foundation of how do I, what is it fundamentally? And then how does it become useful when I attach agents to it? And I use it as this persistent shared memory, right? This optimizable business process graph that's the fundamental concept. There's a few different ways to achieve it. But I'll pause there for any comments questions that you might have. 

14:03 | Amit
This sounds good. But I think the question will be, how is the most critical one? First of all? And the second thing is that accuracy of those response or validation, that, who is saying that whatever is the response is correct? I think you can get a response. You can capture that, but is it correct or not correct, right? For the future use? How do we add validations against those responses that we are capturing, right? And if we are variance in the response, who decides that, which one I should keep? Which one I should discard? I think those kinds of it goes back to how do we set up the evals around these model interactions? Right? So I think it will be good to see the structure, what you have implemented with others, to understand how you're putting the. 

15:03 | Timothy
Harness. 

15:05 | Amit
and the evals around this agent? 

15:09 | Timothy
Yeah. I think I'll answer your second question first because it's more straightforward than the first. Your second question around, how do we decide what is truth in this emergent kind of process graph, right? How do we audit it? How do we control it to make sure that the agents haven't hallucinated their way to a perceived optimal path that they're reusing over and over again. But in reality, it's not actually what we want. There are three kind of channels that you can go through for that. One of them is agent as a judge, which is the most useful option in fully automated autonomous processes that don't have a human in the loop. If you have a customer who's engaging with your chat bot and they're asking questions. The second the agent responds with an answer, the user is going to have some say about that answer, right? It wasn't what I wanted. It is what I wanted. They can be quite blunt quite frankly and that bluntness is useful as sentiment analysis data to tell us how well our pipeline is performing in a truly autonomous no human in the loop scenario. We're having agents talk to agents to automate processes. We don't get that feedback, right? So you introduce this idea of an agent as a judge to evaluate what happened, to look back upon the trace, to look back at the query executions, and then they are what they are, they happened as they happened. But now we can write, if you picture a graph with nodes and relationships, and we're modeling this process as a traversable graph, that path that took us from point a to point B that wasn't the right path. So there's a weight now on that relationship. And the agent as a judge is empowered to adjust that weight and reduce the probability of that path being selected in the future. So, hey, that didn't quite do what we wanted. I see, you know, the agent that executed this decision could only see the one step in front of them, but I now have access to the full trace and that the last mile of that decision didn't take us where we wanted to go here was the junction point. Let me reduce the weight on that relationship. So that the future decision making is steered this way. Agent as a judge. Option number two is what I've alluded to already. If there is some human in the loop interaction, either a customer talking to a chat bot or one of your own employees that's interacting with this thing as a kind of coworker or like an assistant. That data that comes off of that user is very useful. You can do it. Quite literally with like a thumbs up, thumbs down in the UI where we like just capture a boolean metric. But you can also scrape their responses for sentiment analysis and say, hey, this customer was cursing out our bot because it wasn't doing what it wanted them to do that's useful data, right? So that's option number two is kind of getting back the feedback from the users either explicitly or implicitly. Option number three is just literally having a dedicated data admin, like a business aware team of experts in your business in your processes. That as this tree is growing in your garden, they have the pruning clippers, they're going through that's. Not right? That's not, right? That violates this policy that's not adhering to whatever. And then you can plug into those relationships. You can reduce their weight. And even if you really wanted to, you can add context on the relationship. Hey, this weight is low because of X, y and Z reasons. This has been decided by an arbiter, you know, an authoritative arbiter, do not do this again. I'm leaving it in the graph so that if we just prune it, if we just get rid of it, they're liable to recreate it. But if we have it, there is like no established precedent, this is bad. Do not go down this road. When you encounter this scenario, you're met with this choice. This is the wrong decision. Take that one. Now that's useful, right? So you have agent as a judge, you have user sentiment feeding back into this thing for the performance. And then you also have the, you know, curated human employee whose job it is to kind of maintain this tree, right? Those are the three ways that I would personally go initially to keep this thing under control. How was your first question? That's a bigger question? So there are a couple of different options available to you today. It is a bit of a kind of work with our services to build it out and we kind of get embedded in your processes and we help you build it. There are a number of accelerators for that today. Neocarto, you've heard mentioned virtual graph might be another one that you hear. And today, those will get you started. But a lot of the kind of downstream is we're gonna help you build it? Because we have experience building it bespoke for other customers and we'll kind of guide you down the right path. What is actively in process right now, specifically with neocarta, is we are evolving it to the level where it is the go to accelerator for this process. So if you want to. Kind of hit your cart to something and have it be the way forward that we're envisioning being the way forward for building up these semantic layers in the most automated fashion with the most software accelerator support. Neocarta is that thing going forward, right? You'll start to see blog posts coming out about it. It's getting significant investment internally, but I want to be transparent with you. The state that it is in today is what we call a labs project. It's from our innovation hub. So your mileage may vary with implementing it as it is today. But it is the foundation from which we have built multiple semantic layers in the past already. And I can't name customers necessarily. I'll leave that to Sam to litigate which of those we can actually say. But, you know, we have done this multiple times already with neocarta as the start. And if you have someone like young carlo helping you out, who is a former colleague of mine. We used to work on the same team. I think, very highly of him. He would be able to kind of guide you through that process of, okay, here's, our starting point. How do we evolve it into something that's truly enterprise scale? 

20:53 | Amit
Will you be able to show us what that looks like at a kind of a design or architecture level? What is that just for us to understand what you're talking about? Yeah? 

21:04 | Timothy
I think Sam's plugged it up right now. Sure. Yeah. So at a fundamental level, you have all of your source systems. And the first objective is to, how do I get the information about the schema of those source systems into my graph? That's the very first place where neocarta steps in or virtual graph? These are two slightly different offerings but they can do very similar things here. They just have different mechanisms under the hood that we can tease out at a later time. But fundamentally, all they're doing is I will query these source systems for their schemas and that can be through a direct API call to something that has like a schema reporting endpoint, that can be through one of the more cool ways that we do it is if you don't have access to just like a schema dump, you can actually just feed the query logs into neocarta and it will analyze all of the queries that are showing up in the frequency with which they show up, and then extract the patterns that then it can use to intuit the schema of the source system based on the queries that are being executed against it. So you can then get that. But the goal here is for all of my disparate source systems, neocarta has a suite of connectors that you can then plug in. Hey, here's my source system, go talk to it. Those connectors will scrape the schema, but only the schema. This is a zero instance level data copy operation that's very important. It will scrape the schemas and then draw a map within Neo4J for J. Hey, here's all my databases within each database. There's this table within each table. There's this column, right? And then all of that is annotated with descriptive attribution to say, okay, that column is some abbreviated shorthand, what is it actually right? To a human readable? But more importantly agent readable, documentation degree? What is this step two? Is your data catalog, your ability to take your business terminology and then marry it to the schema data? Okay? When my customer says they want to, when a user says they want to ask a question about a customer? Where does customer data live in my database graph? In my enterprise? The word customer is a business term. It's tied to business processes. And it's also in this first step tied to certain tables, certain databases here's, where you store, you know, customer three initial profile here's, where you store the transactional data for customer purchase history here's, where we store X, y and Z, right? So now, this node in the graph and I'm oversimplifying a little bit. 

23:30 | Amit
But what is, yeah, that's what I was going to ask, how do you, what is the methodology for that you mentioned ontologies here? Is that the layer you're talking about where you're defining the rules, that is an option, what are you using for that? 

23:47 | Timothy
So there's a couple different options here. If you already have a business ontology, which many of our customers do, we can just inject that and it has all of the associations between these terms already stored. A lot of people don't have that. So now we get into a different step where we are taking any documentation that you have any unstructured documentation, your internal atlassian, your confluence, your slack messages, your, whatever you want to feed into this thing. And then we can parse all of that to extract out a domain ontology, right of here's, the terms here's, how they relate. And then from these terms, we can then tie them to nodes within… our source system map, right? Some of that is going to be automated where we can say, hey, it's very obvious in this confluence that there's a process document that tells you how to go about doing this business process. And it says when you want to do X process, you query this table. Done that's a hard link, right? But some of this might also be a iterative work that you can improve upon over time as you say, okay, the graph wasn't aware from the data that we fed in. Sometimes if you don't feed the data in, that has the answer to the question, then it won't appear on the other side, right? So you can then as a expert in your business, add in these links, no, when someone says this business term nowhere in the data that we fed in to build this ontology. Did it mention that was a hard link to this database and these business processes, but I, as the domain expert can go in and reify those associations. 

25:17 | Amit
So the agent is looking at ontology to understand the data all the time or is it like you're importing the rules of the ontology into the semantic layer, it's. 

25:31 | Timothy
into the semantic layer. So all that's in the semantic layer, it's your business terms graphed. And specifically, that business term graph is then linked to source systems and their maps. So what the agent does is it wakes up, it receives a question and it says, okay, this question is about X, y and Z. Let me grab the business terms related to X, y and Z. I see those business terms now. Let me traverse. What are the business processes that I have in the graph? I hop over to business processes. What are the database tables in the graph related to these business terms? What is the relationship of these business terms to one another? How do they associate to one another? The things that sit in between business term, a and B? What are their business processes? What are their database tables or sources of information that I can query that have information about that? So it gets the map first, what's the relevant map? The agent number one who sees this question for the first time, might burn a handful more tokens kind of exploring options. All right. I can query this table? I can query that table. I can go to this confluence and grab that article. I can go to here, X, y and Z, right? To get information. So it pulls that information, it constructs a response and it mints it for the user, right? Where this gets efficient is over time that agent's response to that question. And the methodology that they used to achieve it is persisted and stored alongside a question node that sits in the graph. And what did it do step by step, hop by hop, a traversable, what did I do to answer that question? What was the evaluation at every point? Everything that I pulled back? What was the user sentiment? What was the metrics on the query? Okay. So now the next agent doesn't need to redo that work. The first agent did the exploration, it did the innovation. The next agent can say, okay, I now have a process that I know got to an outcome that was desirable or undesirable potentially, if that's what's captured, if the user just leaves because they're frustrated right now, that agent can then evolve that without needing to re query. It's like, okay, I don't need to do X step that was not desirable. I can do y step that was better. I don't need to run a query that the first agent ran, I can run this other query. 

27:36 | Amit
So, for example, if we don't have the ontologies defined, do you work with the business unit to work to define the ontologies first… that? 

27:47 | Timothy
Is a good first step. It absolutely is helpful. I don't think it necessarily has to be first, this can be a parallel initiative, right? The ingestion of the schema map can happen independently from the ingestion of the ontology, but at some point you want to marry them in some critical places just so that there is that association to draw, right? But those can be either one then the other, or they can literally happen in parallel and they can be from your business experts or we can help you automate pipelines which we have tools to do so to pull that ontology out of any data that you just have, right? What were the queries that you've run? What are your query logs? What does your business process documentation say? What are your audit logs for your employees, who were performing certain processes, what was left behind from those processes that we can then pull in consume? And then it extracts an ontology of business terms from it. Whatever you have to start to seed that, whatever's like reified true fact within your enterprise that's already in use is obviously useful if you have a data dictionary, great, but if not, we can help you build one, but it's always better to see if we can start from what you already have somewhere even if it's a fledgling form and evolve that. 

28:56 | Pablo
And I got a question. So let's say we start with what we already have this feedback loop that you're talking about. Is it purely based on customer interactions like them leaving or saying something? Or how does that feedback loop work? And how does it not learn wrong patterns to questions asked by the user? 

29:20 | Timothy
Yeah, we touched on that a little bit earlier, but I'll restate it's. The three options that I said before, right there's, the user input. You know, what was their sentiment? Did they thumbs up, thumbs down if you want to go that route or did they just leave, right? That's some of the things that you can scrape out. Then option two is agent as a judge. This evaluator that goes by, okay, I now see the road that was walked. Let me evaluate each step and see how it performed. And that evaluation is fed all kinds of information, right? What was the performance of each query that was issued when a query was issued against source system a? And it ran for 30 seconds and consumed gigabytes and gigabytes of memory? And the end result was a mediocre user sentiment that to me, that combination of metrics that weights that decision in a specific way in my mind. Hey, I guess this kind of got to where the user wanted. But maybe there's a better option. Maybe there's a different way to get to the answer that's more efficient or this is the way to get to the answer, it got what the user wanted. But this query needs some optimization. You know, we've got the query score here's. What the last agent ran, it ran for 30 seconds. It consumed too much resource and. 

30:24 | Pablo
that's. 

30:24 | Timothy
kind of. 

30:24 | Pablo
What I'm wanting to touch on too is like, yeah, they got the right answer, but really, it's wrong. Right? Yeah. 

30:34 | Timothy
So, it's wrong in what way? Clarify that for me as? 

30:37 | Pablo
In say, I'm a user? I don't know much about what I'm asking? I ask it, I get the answer. Great. Thank you. The answer was wrong. It pointed me into a wrong direction. How does that feedback loop that's reinforcing that wrong answer? That I had no idea that it was wrong. Does that make sense? It's. 

30:58 | Timothy
reinforced in that instance with that individual. But if you zoom out and aggregate across many individuals, that one path where that one person was happy with the wrong answer, it starts to be outweighed by the majority of use cases where other people have said, no, that's not quite right? So there is going to be some noise in the system. But it's a stochastic problem. At this point. We're running the statistics and the probability of, is this the right answer based on an aggregate of user sentiment now that works after a long period of time, but you want it sooner than that. And that's where that third branch of the three comes in, you know, you've got your agent as a judge, you've got your user sentiment, but you've also got your dbas, right? Your database admins, your business experts who are administrators of this system, and you can set up alerts and triggers for what kind of catches your eye as potentially problematic. And now, here comes your expert analyzer, I apologize and they go through and say, hey, that user was happy. But in reality, this doesn't answer the question for X, y and Z reasons, manually drop the weight of that with a rationale. And now the next agent that comes to that junction point, that decision making can actually see the experts analysis of, no, I have dropped this weight. Do not choose this path. Do not remake this path. Here is the justification and what you should do instead. And now that is not in the context of every agent all of the time, it only enters the context of an agent who approaches that decision point and is forced to make a choice. So that's where this starts to drop the token counts, right? You don't need to have every business rule present in every agent's context all of the time. That's impossible. What you need to do is provide precise and meaningful insight at the points where the agent is currently at in the process that it's executing. So that's how we do that, right? So there's those three possible options for how to input that. But this is a tree in a garden. The analogy is appropriate. You need a gardener, right? You need gardeners to go through that, and you have the users, you have the agents as judge, and you have your business process experts who are going to sit there as arbiters and administers of the system. 

33:15 | Pablo
Okay. Thank you. 

33:22 | Dean
Thanks Tim. Any other questions related to kind of a high level, how we approach a semantic layer, incorporate ontologies? Et. 

33:33 | Timothy
Cetera. No? 

33:36 | Amit
This is really good information and I think our thought process is around the same direction as well. I think that's… why so many questions were there. And one last question I may have is that you mentioned virtual graphs. What do you mean by virtual graph here? Yeah? 

33:59 | Timothy
If. 

33:59 | Amit
I may say, of course. 

34:01 | Timothy
The nomenclature can be a little bit confusing here. It's just another offering by Neo4J. Neokarta. Is one software option to achieve this, virtual graph is another software option that does things slightly differently. It's a bit nuanced when to use one over the other. And when you are working with someone like a Yancarlo, they'll help you tease that out. The fundamental difference is with virtual graphs, we are still storing kind of your schema map as a graph. But when you issue cypher, our native query language, against that schema graph, the cypher is translated in real time and through a translation layer that turns that cypher into whatever query language needs to be for the source system that actually stores the data. So you can write cypher, the cipher as needed will be chunked up and transformed into SQL. And then that SQL will fire against your source system and come back. But you only ever wrote the one cipher query, right? It's this query transformation approach where the official query language of the solution is cipher. Neocarta. Takes a slightly different approach. We ingest your schema map as a graph. We store it in the graph. We have all of our connectors to help you do that, but then we're only providing the context of where the data lives and what it's about and what purpose it serves and how to use it. The agent is then empowered to then create or fire API calls against known apis, right? But the agent executes the transaction directly against the source system. It doesn't issue cypher. It issues the native query language of the system that it's targeting to retrieve data from. So, rather than a transformation step, sitting in the middle, the agent is empowered to invoke apis directly or to fire SQL queries directly. And all of those transactions that it chooses to do are stored in the graph and optimized in the way that we've described so far. But it's that slightly different approach, right? Do I write cypher and have it transform magically on the back end to pull back my data as if it was in the graph, natively, virtual graph, right? Or do I create this, you? 

36:02 | Amit
Know, semantic? 

36:02 | Timothy
Layer that exists purely to provide context. And then in that context is the invocation the instructions for the invocation methodologies for those various source systems. And the agent will then invoke those source systems directly that's the neocarta approach. They're, very similar and it's a bit kind of nuanced and in the weeds for this discussion. But since you asked that's kind of your high level differentiator, and. 

36:28 | Sam
the other way to think about it is everybody's talking about zero copy, right? So you have to make trade offs and decisions on whether to leverage the virtual graph to hit. You can either move the source systems and not move the data or you choose to materialize the data in the graph. If you have performance requirements that dictate I need performance to be within a certain number of milliseconds right? Because I want snappy responses. So you have that capability to leave the data where it's at leverage the virtual graph for workloads that don't require immediate responses or materialize… the data in the graph for when you need very snappy responses. Yeah, I want. 

37:21 | Timothy
to quickly clarify because it's almost sounded like he was saying that neocarta materializes the data while virtual graphs doesn't neither one of them materializes the data inherently. What Sam's getting at there is once you've been using a system like this for a long time, either neocarta or virtual graph, whatever you choose to use as your implementation strategy, you get this kind of insight of I've kind of optimized these queries to the best of my ability as an agent. And some of them still aren't quite what I want them to be, right? I run this federated query out of the source system. It takes forever to return just because that system's always bogged down or I'm asking the kinds of questions that just aren't answerable in a traditional tabular database, right? It just doesn't have the structure to ask to answer the question that I'm asking. And so I start to surface these insights and that starts to be a justification for saying we were zero copy. But here are some very strategic locations now data driven that say, hey, maybe we want to pull this data into the graph. So it's an immediate read time transaction from the agent natively right now, it's fast. Now it's capable. 

38:26 | Sam
Yeah. And by the way that exists today, like there's some things that chip is doing in crew analysis and that are multi hop queries that a databricks or a traditional rdbms cannot solve for. 

38:47 | Timothy
We're talking. 

38:47 | Sam
About delay propagation across a flight network. You can't do that kind of stuff in traditional relational databases. So you have to persist that in the graph. You've got to run that analysis in the graph natively? 

39:03 | Amit
Yeah. I think we definitely have that context and that's why I think we feel the power of graph database. One last question, maybe around simulation, right? So basically, what kind of a simulation, I can build around the new for J graph database. For example, I want to simulate certain delay scenarios and see the impact before I pick what, which solution I want to go for, right? Or I want to have agents simulate something, build the reasoning behind that, present it to the user. And user can pick from those options, right? To solve certain business use case. How will we solve with graph… database to support those kinds of simulation? 

40:02 | Timothy
I think you almost kind of get that for free. And I say that carefully but confidently because once you've stood up a version of this, a lightweight version that hasn't lived for very long. So it doesn't have that rich history. The input is always going to be some prompt sent to an agent, right? And that agent can be a monolith or it can have an army of sub agents that it's delegating tasks out to. But at the end of the day, you're feeding in a prompt. So if you have a list of simulated scenarios that you want to curate and have those initial prompts, you can go ahead and just create a loop, create a harness very easily that fires those prompts in with whatever information necessary to do them. And then some response will come back. Now, if it's a multi touch conversation at that point, maybe I would stand up another agent or have a testing, you know, I want to simulate a simulation where you have a body of employees who want to do this themselves, who are more experienced, but you can have a kind of agent stood up that has access to the information to kind of go through this process and it can then simulate your user of the agent comes back and says X y and Z. And it can go not really because it has access to the golden answers, right? It knows that it's acting as a simulator and it has access to the golden answer and it's kind of going through and saying no, that's not quite what I want, right? That doesn't quite do what I need. And then it walks through this process. And because it's fully automated, you could just let that run overnight and build out your seeding graph to start with. I've not personally and I'll be transparent with you. Not personally played around with that too much. Maybe someone else in the company has, we can track them down if they have. But historically it hasn't been as necessary to do that, but it's something to explore and that's how I would approach exploring it. I've got. 

41:49 | Sam
a clarifying question though, Amit, were you asking the question in relation to simulating the knowledge layer, the semantic layer, the output? Or were you talking about simulating different scenarios of a flight network and being able? 

42:06 | Timothy
To. 

42:06 | Amit
apply that. The later one basically, for example, I have a weather coming, right? I want to run through different objective function to mitigate that delay, right? I want to, you know, and I want with the graph database, you touched upon delay propagation, right? I want to see, to mitigate this. If I mitigate this delay through this objective function, what's my impact to my network is, or if I simulate through this, what's my impact to the network, that means that I need, I don't want to modify my original graph or the data on the graph, right? But I want to create a virtual layer of that or simulated layer of that where I can apply those changes on the graph and see the impact without actually implementing that change on the graph on the live graph, right? So, how would we simulate the same scenario? 

43:09 | Yancarlo
Yancarlo? 

43:10 | Sam
You want to jump in and describe what we're doing today? Yeah. 

43:14 | Yancarlo
So, this is something that the American airlines team is actually doing today. It's part of the work with Nemo, the crew vision project where they are simulating arrival delays in the network and they try to determine what are the riskier, what are the most at risk connections or what are the more at risk connections that are going to cause? I don't want to, you know, I don't want to, you know, I don't want to, you know, tail swaps and how those affect the crew, right? So they basically load all the flights of a schedule into the graph. And like you're saying, they're not really modifying the graph. They're using graph algorithms to do different types of projections and then run different scenarios. And with that, you're not modifying the database, but you are modifying the projections that you do, right? And there's a lot of good material that we can get for you as well on what the Nemo team is doing, but this is more related on delay propagation. 

44:09 | Amit
Okay. And they're doing this, basically loading the data in memory and then running these simulations in memory, basically, right in memory. 

44:17 | Yancarlo
Yeah, using our graph analytics offering. Yeah. 

44:20 | Amit
Graph analytics offering. Okay. Yeah, the. 

44:24 | Timothy
Distinguishing point there is that, that's a more traditional graph use case that's been kind of our bread and butter for decades at this point, right? That's separate from semantic layer. So, the beauty about semantic layer is you can have targeted graph use cases and have those be source systems that your semantic layer is aware of. So now you become the graph of graphs. You have your traditional rdbms source systems over here, you have your confluence, everything we've talked about. But then you can have three or four different Neo4J for J solutions as well that exist as source system inputs. And now an arbitrary user talks to your semantic layer agent and says, hey, I need to simulate this event. 

45:00 | Sam
And it, 

45:00 | Timothy
knows, the way to do that is by going to Neo4J database X and running this suite of queries, because I've simulated this 100 times before, right? So now you get access to that shared memory of how to simulate, and you get access to, I know what Neo4J for J database has, the data I need to perform that simulation. So it's a traditional Neo4J for J use case that you would typically just have a dashboard or run cypher queries to run that simulation. But now it is a source system that your semantic layer is aware of and can access and can invoke that's how those two kind of marry. But the distinction is that's a traditional graph use case, it would live in its own Neo4J for J DB. Your semantic layer sits above that, yep. 

45:40 | Amit
Yep. Sounds good. Thank you so much. This is a lot of information to digest. So, thank you so much for providing all this information. 

45:50 | Sam
Here's, one more little bit, right? Like just to get you guys a little bit more comfortable on like how we work with Aws, right? Can you see the screen? There's five different ways that we connect, right? So these are the different connectors, right? So. 

46:07 | Amit
You have the kafka connector for MSK, right? 

46:11 | Sam
Yeah, right. So we can do all that, right? There's, another kind of view of the ecosystem, right? So, I mean, the bottom line is like we've got, you know, so many customers who are already using us in Aws. We've got, you know, connections to all these different components of the Aws portfolio. So it's just a matter of like deciding… hey, do we want to use neptune because it's already part of the Aws portfolio? Or do we want to leverage Neo4J for J because it's already being used in American and it's got a much more robust portfolio and capabilities related to a semantic layer. They were thinking about it much more strategically and it's more performant right there's, things that we can do there's. Things that chip can do and analyzing delay propagation across multiple hops that neptune's going to just candidly break down. Yeah. So I mean, those are the things that you guys got to consider, right? Yeah. 

47:23 | Amit
Definitely. I think this, I think we see that there's a seamless integration to Neo4J through Aws. Yeah. And I think we should be able to definitely go on a path to do a POC for the semantic layer basically, right? 

47:40 | Sam
Not to mention like we're already in the marketplace. So like our enterprise edition is already there, aura is already there. This is what's being run today in azure, but it's also available in Aws as well. So, you know, we can deploy where you need it to. We're flexible. 

48:00 | Amit
So, yeah, this sounds really great. Thank you, Sam. And we'll get back and analyze the scope for the POC and we'll definitely touch base with you that. How do we get going on with the next steps? 

48:16 | Sam
All right. Great. Okay. We've got 10 minutes left, but I think we've covered everything that you wanted to cover. Yeah. Are there any other questions before we let you get back to Aws training? No, I. 

48:29 | Amit
Think we're all good for today? We'll touch base with you all again soon. Yeah. 

48:36 | Timothy
It was a lot to digest. It was great talking with you, Amit. I do encourage you to check out those articles that Sam had sent you on the invite. I think that they are a great resource. Obviously, this was a dense hour. So if you want to kind of digest it a bit more slowly, a lot of what we talked about is captured in those articles. Yeah. 

48:52 | Sam
And I'll I recorded this, so I'll send you guys a recording so that your other team members can review it. 

48:59 | Amit
Sounds good. Thank you, Sam. Thanks Tim for your insight. Thank you. Can you also attach the presentation? 

49:06 | Timothy
To. 

49:06 | Amit
the slides? Yes, I'll do that. 

49:10 | Timothy
Email, thank you. 

49:11 | Sam
You got it. Thank you. All right. Thanks, everyone. Appreciate the time. Thank you. We'll talk soon. 