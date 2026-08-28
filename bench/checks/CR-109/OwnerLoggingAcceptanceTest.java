package org.springframework.samples.petclinic.customers.web;

import java.util.List;
import java.util.Optional;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.samples.petclinic.customers.model.Owner;
import org.springframework.samples.petclinic.customers.model.OwnerRepository;
import org.springframework.samples.petclinic.customers.web.mapper.OwnerEntityMapper;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Acceptance check for CR-109: an owner's contact details never reach the log, and the
 * update is still recorded.
 */
@WebMvcTest(OwnerResource.class)
@ActiveProfiles("test")
class OwnerLoggingAcceptanceTest {

    private static final String ADDRESS = "31 Confidential Row";

    private static final String CITY = "Privatetown";

    private static final String TELEPHONE = "6085551023";

    private static final int OWNER_ID = 4242;

    private static final String BODY = "{\"firstName\":\"George\",\"lastName\":\"Franklin\","
        + "\"address\":\"" + ADDRESS + "\",\"city\":\"" + CITY + "\","
        + "\"telephone\":\"" + TELEPHONE + "\"}";

    @Autowired
    MockMvc mvc;

    @MockitoBean
    OwnerRepository ownerRepository;

    @MockitoBean
    OwnerEntityMapper ownerEntityMapper;

    private ListAppender<ILoggingEvent> appender;

    private Logger rootLogger() {
        return (Logger) LoggerFactory.getLogger(org.slf4j.Logger.ROOT_LOGGER_NAME);
    }

    @BeforeEach
    void captureTheLog() {
        appender = new ListAppender<>();
        appender.start();
        Logger root = rootLogger();
        root.setLevel(Level.INFO);
        root.addAppender(appender);
    }

    @AfterEach
    void releaseTheLog() {
        rootLogger().detachAppender(appender);
        appender.stop();
    }

    private Owner anOwner() {
        Owner owner = new Owner();
        owner.setFirstName("George");
        owner.setLastName("Franklin");
        owner.setAddress(ADDRESS);
        owner.setCity(CITY);
        owner.setTelephone(TELEPHONE);
        return owner;
    }

    @Test
    void shouldNotWriteContactDetailsToTheLog() throws Exception {
        Owner owner = anOwner();
        given(ownerRepository.findById(OWNER_ID)).willReturn(Optional.of(owner));
        given(ownerEntityMapper.map(any(Owner.class), any(OwnerRequest.class))).willReturn(owner);
        given(ownerRepository.save(any(Owner.class))).willReturn(owner);

        mvc.perform(put("/owners/" + OWNER_ID)
                .contentType(MediaType.APPLICATION_JSON).content(BODY))
            .andExpect(status().isNoContent());

        List<ILoggingEvent> events = List.copyOf(appender.list);
        for (ILoggingEvent event : events) {
            String message = event.getFormattedMessage();
            assertThat(message).as("no log line may carry the address").doesNotContain(ADDRESS);
            assertThat(message).as("no log line may carry the city").doesNotContain(CITY);
            assertThat(message).as("no log line may carry the telephone")
                .doesNotContain(TELEPHONE);
        }

        assertThat(events)
            .as("an info line must still record the update, identifying the owner")
            .anyMatch(event ->
                event.getLevel() == Level.INFO
                    && event.getFormattedMessage().contains(Integer.toString(OWNER_ID)));
    }
}
