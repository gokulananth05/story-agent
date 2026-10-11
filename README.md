# Sleepy Story Time

A bedtime storyteller for children up to age 5. A parent types a story idea, picks a language and a sleep timer, and the agent writes a gentle story and narrates it aloud. The story gets slower and quieter as it goes, and ends with a goodnight.

Built for the AWS Builder Center **Build an Agent Weekend Challenge**.

![Screenshot of the app](docs/screenshot.png)

## Who it is for

Parents and carers who run out of bedtime stories, and who don't want a bright screen keeping a child awake. The design is audio-first: after the story starts, the page fades to almost black.

## What makes it different

- **The timer shapes the story.** The story is written in three parts (opening, middle, winding down). Each part is narrated more slowly than the last, with longer pauses between sentences.
- **Sleep-first design.** No pictures and no bright screen. Tap anywhere to bring the page back.
- **Soft sounds.** Gentle rain, ocean waves or a soft hum, generated in the browser. They fade in at the start and fade out slowly after the story ends.
- **English and Hindi.** Each language has its own narrator voice.
- **Child-safe by design.** The model is instructed to use simple words and never include anything scary, violent or sad.

## How it works

```
Web page (index.html)
   |  POST {idea, minutes, language, passcode}
   v
Lambda Function URL
   |
   v
AWS Lambda (lambda_function.py)
   |-- Amazon Bedrock (Amazon Nova): writes each part of the story
   |       (checks the word count and asks for a rewrite if a part is too short)
   |-- Amazon Polly (neural voice): narrates each part at its own pace
   |-- Amazon S3 (private bucket): stores the mp3
   v
Temporary link (1 hour) returned to the page, which plays the story
```

### AWS services used

| Service | Role |
|---|---|
| AWS Lambda | Runs the agent code, exposed through a Function URL |
| Amazon Bedrock (Amazon Nova) | Writes the story |
| Amazon Polly | Turns the story into speech |
| Amazon S3 | Stores the audio in a private bucket |
| IAM | Gives the Lambda role access to only what it needs |

## Files

- `lambda_function.py` - the agent (Lambda handler)
- `index.html` - the web page (open it in a browser; no server needed)

## Setup

1. Create a **private** S3 bucket.
2. Create a Lambda function (recent Python runtime), timeout 5 minutes, memory 256 MB.
3. Give its execution role access to Bedrock, Polly and your bucket (`s3:PutObject`, `s3:GetObject` on the bucket only).
4. Enable access to an Amazon Nova model in Bedrock, and set `MODEL_ID` in `lambda_function.py` to the model or inference profile ID from your console.
5. Add environment variables:
   - `BUCKET_NAME` - your bucket name
   - `ACCESS_CODE` - a passcode of your choice
6. Create a Function URL with CORS allowing `POST` and the `content-type` header.
7. Open `index.html`, expand **Setup**, and paste your Function URL. Enter your passcode on the page.

## Protecting the deployment

- Requests without the right passcode are rejected.
- The idea is limited to 100 characters and the length to 1-10 minutes.
- The bucket is private. The page receives a temporary link to one file.
- Set an AWS budget alert, and consider limiting Lambda concurrency.

## Honest limits

- Story length is approximate. The agent aims for the requested time using a measured words-per-minute value, and typically lands within about 10-15%.
- Hindi story quality depends on the model. Review stories before relying on them.
- The soft sounds are synthesized noise, not recordings.

## Ideas for later

- More languages
- Remembering the child's name and favorite character between nights
- Weaving the child's day into the story
