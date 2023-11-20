import { IMailProvider, IMessage } from "../IMailProvider";
import nodemailer from "nodemailer";
import { Mail } from "nodemailer/lib/mailer";
export class MailTrapProvider implements IMailProvider {
  private transporter: Mail;

  constructor() {
    this.transporter = nodemailer.createTransporter({
      host: "mailtrap.smtp.io",
      port: 2525,
      auth: {
        user: "", //Set user
        pass: "", //Set password
      },
    });
  }

  async sendMail(message: IMessage): Promise<void> {
    await this.transporter.sendMail({
      to: {
        name: message.to.name,
        address: message.to.email,
      },
      from: {
        name: message.to.name,
        address: message.to.email,
      },
      subject: message.subject,
      html: message.body,
    });
  }
}
